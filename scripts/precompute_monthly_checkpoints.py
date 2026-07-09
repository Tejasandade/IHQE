import os
import sys
import json
from datetime import datetime
import pandas as pd
from dateutil.relativedelta import relativedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database.clickhouse_client import ClickHouseClient
from engine.intelligence.mtf_engine import MTFIntelligenceEngine
from pydantic import BaseModel

def generate_checkpoints():
    db = ClickHouseClient()
    
    # Find start and end dates from OHLCV
    res = db.query_df("SELECT min(ts) as min_ts, max(ts) as max_ts FROM ihqe.xauusd_ohlcv")
    if res.empty or pd.isna(res.iloc[0]["min_ts"]):
        print("No OHLCV data found.")
        return
        
    start_ts = pd.to_datetime(res.iloc[0]["min_ts"]).replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    end_ts = pd.to_datetime(res.iloc[0]["max_ts"]).replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    
    print(f"Generating checkpoints from {start_ts} to {end_ts}")
    
    engine = MTFIntelligenceEngine()
    
    current_month = start_ts
    rows_to_insert = []
    
    while current_month <= end_ts:
        print(f"Processing checkpoint: {current_month.strftime('%Y-%m-%d')}")
        
        # 1. MTF Intelligence Engine State
        state = engine.run(as_of_ts=current_month)
        
        # 2. Overlays
        bos_events = {}
        fib_grids = {}
        fvg_events = {}
        
        for tf in engine.timeframes:
            df_bos = db.get_bos_events(tf, active_only=True, as_of_ts=current_month)
            bos_events[tf] = df_bos.to_dict('records') if not df_bos.empty else []
            
            df_fib = db.get_fib_grids(tf, active_only=True, as_of_ts=current_month)
            fib_grids[tf] = df_fib.to_dict('records') if not df_fib.empty else []
            
            df_fvg = db.get_fvg_events(tf, as_of_ts=current_month)
            if not df_fvg.empty:
                as_of_ts_pd = pd.to_datetime(current_month, utc=True)
                df_fvg['ts_mitigated'] = pd.to_datetime(df_fvg['ts_mitigated'], utc=True)
                df_fvg = df_fvg[(pd.isna(df_fvg['ts_mitigated'])) | (df_fvg['ts_mitigated'] > as_of_ts_pd)]
                # Ensure all timestamps in df_fvg are timezone-naive or converted correctly
                for col in df_fvg.columns:
                    if pd.api.types.is_datetime64_any_dtype(df_fvg[col]):
                        df_fvg[col] = df_fvg[col].dt.tz_convert('UTC').dt.tz_localize(None)
                fvg_events[tf] = df_fvg.to_dict('records')
            else:
                fvg_events[tf] = []
                
        # 3. Cascade states
        df_cascade = db.get_cascade_states(as_of_ts=current_month)
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
                
        state["overlays"] = {
            "bos": bos_events,
            "fib": fib_grids,
            "fvg": fvg_events
        }
        state["cascade"] = cascade
        
        def default_serializer(obj):
            if isinstance(obj, pd.Timestamp) or isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, BaseModel):
                return obj.model_dump()
            raise TypeError(f"Type {type(obj)} not serializable")
            
        state_json = json.dumps(state, default=default_serializer)
        
        rows_to_insert.append({
            "month": current_month.date(),
            "state": state_json
        })
        
        # Insert in chunks of 12 to save memory
        if len(rows_to_insert) >= 12:
            db.execute("INSERT INTO ihqe.simulation_monthly_checkpoints (month, state) VALUES", rows_to_insert)
            rows_to_insert = []
            
        current_month += relativedelta(months=1)
        
    if rows_to_insert:
        db.execute("INSERT INTO ihqe.simulation_monthly_checkpoints (month, state) VALUES", rows_to_insert)
        
    print("Checkpoints generated successfully!")
    db.close()

if __name__ == "__main__":
    db = ClickHouseClient()
    db.execute("TRUNCATE TABLE ihqe.simulation_monthly_checkpoints")
    db.close()
    generate_checkpoints()
