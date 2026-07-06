"""
IHQE — Dukascopy CSV Loader
Reads downloaded CSV files from data/historical/xauusd/ and inserts into ClickHouse xauusd_ohlcv table.
"""

import logging
import os
import sys
import glob
from datetime import datetime
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import settings
from database.clickhouse_client import ClickHouseClient

logger = logging.getLogger(__name__)

BATCH_SIZE = 100_000


def load_csv_file(filepath: str, db: ClickHouseClient) -> tuple[int, int]:
    """Load a single Dukascopy CSV file directly into xauusd_ohlcv.
    
    Dukascopy CSV format:
        timestamp, open, high, low, close, volume
    
    Returns: (inserted_count, skipped_count)
    """
    filename = os.path.basename(filepath).lower()
    
    # Determine timeframe from filename
    if "h4" in filename:
        timeframe = "4H"
    else:
        timeframe = "1H"
    
    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        logger.error(f"Failed to read {filename}: {e}")
        return 0, 0

    if df.empty:
        logger.warning(f"{filename}: Empty file, skipping")
        return 0, 0

    # Normalize column names (dukascopy-node output varies)
    df.columns = [c.strip().lower() for c in df.columns]
    
    # Map common column name variations
    col_map = {}
    for col in df.columns:
        if 'time' in col or 'date' in col:
            col_map[col] = 'timestamp'
        elif col in ('open', 'o'):
            col_map[col] = 'open'
        elif col in ('high', 'h'):
            col_map[col] = 'high'
        elif col in ('low', 'l'):
            col_map[col] = 'low'
        elif col in ('close', 'c'):
            col_map[col] = 'close'
        elif col in ('volume', 'v', 'vol'):
            col_map[col] = 'volume'
    
    df.rename(columns=col_map, inplace=True)
    
    # Check required columns
    required = {'timestamp', 'open', 'high', 'low', 'close'}
    missing = required - set(df.columns)
    if missing:
        logger.error(f"{filename}: Missing columns: {missing}. Available: {list(df.columns)}")
        return 0, 0

    # Parse timestamps — Dukascopy uses millisecond epoch timestamps
    try:
        # Try millisecond epoch first (e.g., 1704067200000)
        if df['timestamp'].dtype in ('int64', 'float64') or df['timestamp'].iloc[0].isdigit():
            df['timestamp'] = pd.to_datetime(df['timestamp'].astype(float), unit='ms', utc=True)
        else:
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    except Exception:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    
    inserted = 0
    skipped = 0
    batch = []

    for _, row in df.iterrows():
        batch.append({
            "ts": row['timestamp'].to_pydatetime(),
            "open": float(row['open']),
            "high": float(row['high']),
            "low": float(row['low']),
            "close": float(row['close']),
            "tick_count": 0,
        })

        if len(batch) >= BATCH_SIZE:
            try:
                db.insert_ohlcv(timeframe, batch)
                inserted += len(batch)
            except Exception as e:
                logger.error(f"Batch insert failed: {e}")
                skipped += len(batch)
            batch = []

    # Insert remaining batch
    if batch:
        try:
            db.insert_ohlcv(timeframe, batch)
            inserted += len(batch)
        except Exception as e:
            logger.error(f"Final batch insert failed: {e}")
            skipped += len(batch)

    return inserted, skipped


def load_all(data_dir: str = None) -> None:
    """Load all Dukascopy CSV files from the historical data directory."""
    if data_dir is None:
        data_dir = str(settings.HISTORICAL_DIR)

    csv_files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    
    if not csv_files:
        logger.error(f"No CSV files found in {data_dir}")
        print(f"[ERROR] No CSV files found in {data_dir}")
        print(f"  Run the downloader first: bash ingestion/dukascopy_downloader.sh")
        return

    db = ClickHouseClient()
    total_inserted = 0
    total_skipped = 0

    print(f"\n{'='*60}")
    print(f"  IHQE Dukascopy Loader")
    print(f"  Files: {len(csv_files)}")
    print(f"  Directory: {data_dir}")
    print(f"{'='*60}\n")
    
    # We delete existing 1H and 4H so we don't have duplicates
    db.delete_ohlcv("1H")
    db.delete_ohlcv("4H")

    for filepath in tqdm(csv_files, desc="Loading CSV files"):
        filename = os.path.basename(filepath)
        inserted, skipped = load_csv_file(filepath, db)
        total_inserted += inserted
        total_skipped += skipped
        logger.info(
            f"[INFO] Loaded {filename}: {inserted:,} candles inserted. Skipped: {skipped:,}."
        )

    print(f"\n{'='*60}")
    print(f"  Load Complete")
    print(f"  Total inserted: {total_inserted:,}")
    print(f"  Total skipped:  {total_skipped:,}")
    print(f"{'='*60}")

    db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    load_all()
