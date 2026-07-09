import json
import requests
from datetime import datetime
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from api.routers.simulation import get_historical_state
from database.clickhouse_client import ClickHouseClient
from engine.intelligence.mtf_engine import MTFIntelligenceEngine

def diff_state():
    state_chk = get_historical_state("2020-01-15T12:00:00Z")
    
    db = ClickHouseClient()
    as_of_ts = datetime.fromisoformat("2020-01-15T12:00:00Z".replace("Z", "+00:00")).replace(tzinfo=None)
    engine = MTFIntelligenceEngine()
    state_full = engine.run(as_of_ts=as_of_ts)
    
    bos_events = {}
    fib_grids = {}
    fvg_events = {}
    for tf in engine.timeframes:
        df_bos = db.get_bos_events(tf, active_only=True, as_of_ts=as_of_ts)
        bos_events[tf] = df_bos.to_dict('records') if not df_bos.empty else []
        df_fib = db.get_fib_grids(tf, active_only=True, as_of_ts=as_of_ts)
        fib_grids[tf] = df_fib.to_dict('records') if not df_fib.empty else []
        df_fvg = db.get_fvg_events(tf, as_of_ts=as_of_ts)
        if not df_fvg.empty:
            as_of_ts_pd = pd.to_datetime(as_of_ts, utc=True)
            df_fvg['ts_mitigated'] = pd.to_datetime(df_fvg['ts_mitigated'], utc=True)
            df_fvg = df_fvg[(pd.isna(df_fvg['ts_mitigated'])) | (df_fvg['ts_mitigated'] > as_of_ts_pd)]
            for col in df_fvg.columns:
                if pd.api.types.is_datetime64_any_dtype(df_fvg[col]):
                    df_fvg[col] = df_fvg[col].dt.tz_convert('UTC').dt.tz_localize(None)
            fvg_events[tf] = df_fvg.to_dict('records')
        else:
            fvg_events[tf] = []
            
    df_cascade = db.get_cascade_states(as_of_ts=as_of_ts)
    cascade = {"swing": [], "scalp_path": [], "scalp_cont": []}
    if not df_cascade.empty:
        for col in df_cascade.columns:
            if pd.api.types.is_datetime64_any_dtype(df_cascade[col]):
                df_cascade[col] = df_cascade[col].dt.tz_convert('UTC').dt.tz_localize(None)
        from api.routers.cascade import _sanitize_records
        records = _sanitize_records(df_cascade)
        cascade["swing"] = [r for r in records if r.get("layer", "swing") == "swing"]
        cascade["scalp_path"] = [r for r in records if r.get("layer") == "scalp_path"]
        cascade["scalp_cont"] = [r for r in records if r.get("layer") == "scalp_cont"]
        
    state_full["overlays"] = {"bos": bos_events, "fib": fib_grids, "fvg": fvg_events}
    state_full["cascade"] = cascade
    
    def default_serializer(obj):
        if isinstance(obj, pd.Timestamp) or isinstance(obj, datetime):
            return obj.isoformat()
        import pydantic
        if isinstance(obj, pydantic.BaseModel):
            return obj.model_dump()
        raise TypeError(f"Type {type(obj)} not serializable")
        
    state_full = json.loads(json.dumps(state_full, default=default_serializer))
    
    # Compare
    for overlay in ["bos", "fib", "fvg"]:
        for tf in engine.timeframes:
            len_chk = len(state_chk["overlays"][overlay].get(tf, []))
            len_full = len(state_full["overlays"][overlay].get(tf, []))
            if len_chk != len_full:
                print(f"Diff in {overlay} {tf}: chk={len_chk}, full={len_full}")

if __name__ == "__main__":
    diff_state()
