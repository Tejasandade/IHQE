"""
IHQE v3 — Cascade, FVG, Fibonacci, BOS API Router
"""

from typing import Optional

from fastapi import APIRouter, Query

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from database.clickhouse_client import ClickHouseClient

router = APIRouter()


def get_db():
    return ClickHouseClient()


@router.get("/cascade/current")
def get_cascade_current():
    """Returns live cascade gate states for all timeframes."""
    db = get_db()
    try:
        df = db.get_cascade_states()
        if df.empty:
            return {"swing": [], "scalp_path": [], "scalp_cont": []}

        records = _sanitize_records(df)

        # Group by layer
        swing = [r for r in records if r.get("layer", "swing") == "swing"]
        scalp_path = [r for r in records if r.get("layer") == "scalp_path"]
        scalp_cont = [r for r in records if r.get("layer") == "scalp_cont"]

        return {
            "swing": swing,
            "scalp_path": scalp_path,
            "scalp_cont": scalp_cont,
        }
    finally:
        db.close()


def _sanitize_records(df) -> list[dict]:
    """Convert a DataFrame to JSON-safe list of dicts.
    
    Handles:
    - datetime → ISO string
    - NaN / NaT → None (JSON null)
    """
    import pandas as pd
    records = df.to_dict("records")
    for r in records:
        for key in list(r.keys()):
            val = r[key]
            # Check NaT first (pandas NaT has isoformat but returns 'NaT')
            if isinstance(val, type(pd.NaT)) or str(val) == 'NaT':
                r[key] = None
            elif isinstance(val, float) and (val != val):  # NaN check
                r[key] = None
            elif hasattr(val, 'isoformat'):
                r[key] = val.isoformat()
    return records


@router.get("/fvg/{timeframe}")
def get_fvg_events(
    timeframe: str,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    """Returns all FVG rectangles (active and mitigated) for overlay."""
    db = get_db()
    try:
        df = db.get_fvg_events(timeframe)
        if df.empty:
            return []
        return _sanitize_records(df)
    finally:
        db.close()


@router.get("/fib_grids/{timeframe}")
def get_fib_grids(
    timeframe: str,
    active_only: bool = Query(False, description="Return only active grids"),
):
    """Returns Fibonacci grid levels for overlay lines."""
    db = get_db()
    try:
        df = db.get_fib_grids(timeframe, active_only=active_only)
        if df.empty:
            return []
        return _sanitize_records(df)
    finally:
        db.close()


@router.get("/bos_events/{timeframe}")
def get_bos_events(
    timeframe: str,
    active_only: bool = Query(False),
    limit: int = Query(None, description="Max BOS events to return (most recent first)"),
):
    """Returns BOS markers for the chart."""
    db = get_db()
    try:
        df = db.get_bos_events(timeframe, active_only=active_only)
        if df.empty:
            return []

        # Limit results for lower timeframes to prevent chart clutter
        # 4H has ~16K events, 1H has ~83K events
        effective_limit = limit
        if effective_limit is None:
            if timeframe == "4H":
                effective_limit = 100
            elif timeframe == "1H":
                effective_limit = 50
        if effective_limit is not None and len(df) > effective_limit:
            df = df.iloc[-effective_limit:]

        return _sanitize_records(df)
    finally:
        db.close()

