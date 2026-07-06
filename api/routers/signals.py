"""
IHQE v3 — Signals API Router
"""

from typing import Optional

from fastapi import APIRouter, Query

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from database.clickhouse_client import ClickHouseClient

router = APIRouter()


def get_db():
    return ClickHouseClient()


def _sanitize_records(df) -> list[dict]:
    """Convert a DataFrame to JSON-safe list of dicts."""
    import pandas as pd
    records = df.to_dict("records")
    for r in records:
        for key in list(r.keys()):
            val = r[key]
            if isinstance(val, type(pd.NaT)) or str(val) == 'NaT':
                r[key] = None
            elif isinstance(val, float) and (val != val):
                r[key] = None
            elif hasattr(val, 'isoformat'):
                r[key] = val.isoformat()
    return records


@router.get("/signals")
def get_signals(
    type: Optional[str] = Query(None, alias="type", description="Trade type: swing | scalp_path | scalp_cont"),
    status: Optional[str] = Query(None, description="Signal status: open | executed | invalidated"),
):
    """Returns current trade signals."""
    db = get_db()
    try:
        df = db.get_trade_signals(trade_type=type, status=status)
        if df.empty:
            return []
        return _sanitize_records(df)
    finally:
        db.close()


@router.get("/signals/history")
def get_signal_history(
    limit: int = Query(50, description="Number of historical signals to return"),
):
    """Returns historical signal outcomes."""
    db = get_db()
    try:
        df = db.get_trade_signals(limit=limit)
        if df.empty:
            return []
        return _sanitize_records(df)
    finally:
        db.close()


@router.get("/trades")
def get_trades(
    type: Optional[str] = Query(None, alias="type", description="Trade type"),
    status: Optional[str] = Query(None, description="Trade status: open | closed"),
    limit: int = Query(100),
):
    """Returns trade records."""
    db = get_db()
    try:
        df = db.get_trades(trade_type=type, status=status, limit=limit)
        if df.empty:
            return []
        return _sanitize_records(df)
    finally:
        db.close()
