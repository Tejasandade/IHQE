"""
IHQE — OHLCV Builder
Rolls up 1H candles from ClickHouse into OHLCV candles for higher timeframes (12M, 3M, 1M, W).
1H and 4H are populated directly by dukascopy_loader.py.
"""

import logging
import os
import sys
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import settings
from database.clickhouse_client import ClickHouseClient

logger = logging.getLogger(__name__)


class OHLCVBuilder:
    """Builds OHLCV candles for higher timeframes from 1H data."""

    def __init__(self, db_client: ClickHouseClient):
        self.db = db_client

    def _resolve_end_date(self, end: str) -> str:
        """Resolve 'today' to actual date string."""
        if end == "today":
            return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        return end

    def _fetch_1h_candles(self, start: str, end: str) -> pd.DataFrame:
        """Fetch 1H candles from ClickHouse to use as base for resampling."""
        end = self._resolve_end_date(end)
        sql = """
            SELECT ts, open, high, low, close
            FROM ihqe.xauusd_ohlcv
            WHERE timeframe = '1H' AND ts >= %(start)s AND ts <= %(end)s
            ORDER BY ts
        """
        df = self.db.query_df(sql, {"start": start, "end": end})
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df.set_index("ts", inplace=True)
            df["open"] = df["open"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            df["close"] = df["close"].astype(float)
        return df

    def _resample(self, candles: pd.DataFrame, rule: str) -> pd.DataFrame:
        """Resample 1H candles into higher timeframes using the given rule."""
        if candles.empty:
            return pd.DataFrame()

        ohlcv = candles.resample(rule).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last"
        })
        
        # Count 1H candles per resampled candle
        count = candles["close"].resample(rule).count()
        ohlcv["tick_count"] = count.astype(int)
        
        # Drop candles with no data
        ohlcv.dropna(subset=["open"], inplace=True)
        ohlcv = ohlcv[ohlcv["tick_count"] > 0]
        
        return ohlcv

    def build(
        self,
        timeframe: str,
        start: str = None,
        end: str = None,
        replace: bool = True,
    ) -> int:
        """Build OHLCV candles for a single timeframe.
        
        Args:
            timeframe: One of the canonical keys from settings.TIMEFRAMES
            start: Start date string (defaults to HISTORY_START)
            end: End date string (defaults to 'today')
            replace: If True, deletes existing data for this timeframe first
            
        Returns: Number of candles inserted
        """
        if timeframe not in settings.TIMEFRAMES:
            raise ValueError(f"Unknown timeframe: {timeframe}. Valid: {list(settings.TIMEFRAMES.keys())}")

        label = settings.TIMEFRAMES[timeframe]["label"]

        if timeframe in ("1H", "4H"):
            # These are populated directly by dukascopy_loader.py
            # Just return the count
            sql = "SELECT count() as cnt FROM ihqe.xauusd_ohlcv WHERE timeframe = %(tf)s"
            df = self.db.query_df(sql, {"tf": timeframe})
            count = df["cnt"].iloc[0] if not df.empty else 0
            logger.info(f"[{timeframe}] Native Dukascopy data: {count:,} candles")
            return count

        start = start or settings.HISTORY_START
        end = end or settings.HISTORY_END
        rule = settings.TIMEFRAMES[timeframe]["resample_rule"]

        logger.info(f"Building {label} ({timeframe}) OHLCV: {start} to {end}")
        
        # Fetch 1H candles as base
        base_candles = self._fetch_1h_candles(start, end)
        if base_candles.empty:
            logger.warning(f"No 1H candle data found for {start} to {end}")
            return 0

        logger.info(f"  Fetched {len(base_candles):,} 1H candles")

        # Resample
        ohlcv = self._resample(base_candles, rule)
        if ohlcv.empty:
            logger.warning(f"No candles produced for {timeframe}")
            return 0

        logger.info(f"  Produced {len(ohlcv):,} candles")

        # Delete existing if replacing
        if replace:
            self.db.delete_ohlcv(timeframe)

        # Convert to list of dicts for insertion
        rows = []
        for ts, row in ohlcv.iterrows():
            rows.append({
                "ts": ts.to_pydatetime(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "tick_count": int(row["tick_count"]),
            })

        # Insert in batches
        batch_size = 50_000
        inserted = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            self.db.insert_ohlcv(timeframe, batch)
            inserted += len(batch)

        logger.info(f"  Inserted {inserted:,} {label} candles")
        return inserted

    def build_all(
        self,
        start: str = None,
        end: str = None,
        replace: bool = True,
    ) -> dict[str, int]:
        """Build OHLCV candles for all 6 timeframes.
        
        Returns: Dict mapping timeframe key to number of candles inserted
        """
        start = start or settings.HISTORY_START
        end = end or settings.HISTORY_END
        
        results = {}
        print(f"\n{'='*60}")
        print(f"  IHQE OHLCV Builder")
        print(f"  Range: {start} to {end}")
        print(f"  Timeframes: {', '.join(settings.TIMEFRAME_CASCADE)}")
        print(f"{'='*60}\n")

        for tf in settings.TIMEFRAME_CASCADE:
            count = self.build(tf, start, end, replace)
            results[tf] = count
            print(f"  [{tf:>3s}] {settings.TIMEFRAMES[tf]['label']:>10s}: {count:>8,} candles")

        print(f"\n{'='*60}")
        total = sum(results.values())
        print(f"  Total candles: {total:,}")
        print(f"{'='*60}")
        
        return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Check if 1H data exists before building
    db = ClickHouseClient()
    df = db.query_df("SELECT count() as cnt FROM ihqe.xauusd_ohlcv WHERE timeframe = '1H'")
    count = df["cnt"].iloc[0] if not df.empty else 0
    if count < 1000:
        print("[ERROR] 1H data not found or insufficient in ClickHouse.")
        print("  Please run the loader first: python ingestion/dukascopy_loader.py")
        db.close()
        sys.exit(1)
        
    builder = OHLCVBuilder(db)
    builder.build_all()
    db.close()
