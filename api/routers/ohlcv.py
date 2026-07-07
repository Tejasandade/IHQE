"""
IHQE v3 — OHLCV API Router
"""

from typing import Optional

from fastapi import APIRouter, Query

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from database.clickhouse_client import ClickHouseClient

router = APIRouter()


def get_db():
    return ClickHouseClient()


@router.get("/ohlcv/{timeframe}")
def get_ohlcv(
    timeframe: str,
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: Optional[int] = Query(None, description="Max candles to return (default: all for swing, 2500 for scalp)"),
):
    """Returns OHLCV candles as JSON array for TradingView chart."""
    db = get_db()
    try:
        df = db.get_ohlcv(timeframe, start=start, end=end)
        if df.empty:
            return []

        # Apply limit — default for sub-weekly timeframes to avoid
        # overloading the frontend chart with 50K-200K candle arrays
        # 4H: 1500 candles ≈ 8 months of data
        # 1H: 250 candles ≈ 10 days of data (clear candle rendering)
        effective_limit = limit
        if effective_limit is None:
            if timeframe == "4H":
                effective_limit = 5000
            elif timeframe == "1H":
                effective_limit = 5000
                
        # Bridge the gap using Tiingo historical REST API to guarantee no missing hours!
        interval_map = {'1H': '1hour', '4H': '4hour'}
        if timeframe in interval_map and not df.empty:
            import requests
            import pandas as pd
            from config.settings import TIINGO_API_TOKEN
            
            last_ts = df.index.max()
            hours_to_add = int(timeframe[0])
            next_ts = last_ts + pd.Timedelta(hours=hours_to_add)
            
            start_date_str = next_ts.strftime('%Y-%m-%dT%H:%M:%S.000Z')
            url = f"https://api.tiingo.com/tiingo/fx/prices?tickers=xauusd&resampleFreq={interval_map[timeframe]}&startDate={start_date_str}&token={TIINGO_API_TOKEN}"
            
            try:
                res = requests.get(url, timeout=3)
                if res.status_code == 200:
                    data = res.json()
                    if data:
                        live_df = pd.DataFrame(data)
                        live_df['ts'] = pd.to_datetime(live_df['date'], utc=True)
                        live_df.set_index('ts', inplace=True)
                        live_df = live_df[['open', 'high', 'low', 'close']]
                        df = pd.concat([df, live_df])
            except Exception as e:
                print(f"Error bridging gap with Tiingo: {e}")

        if effective_limit is not None and len(df) > effective_limit:
            df = df.iloc[-effective_limit:]

        df = df[~df.index.duplicated(keep='last')].sort_index()

        records = []
        for ts, row in df.iterrows():
            records.append({
                "time": int(ts.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
        return records
    finally:
        db.close()

