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

        if effective_limit is not None and len(df) > effective_limit:
            df = df.iloc[-effective_limit:]

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

