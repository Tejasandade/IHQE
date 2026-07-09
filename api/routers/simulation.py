import asyncio
import json
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from database.clickhouse_client import ClickHouseClient
from engine.intelligence.mtf_engine import MTFIntelligenceEngine
import pandas as pd

router = APIRouter(prefix="/simulation", tags=["simulation"])

@router.get("/events")
def get_event_schedule(start_ts: str, end_ts: str):
    """
    Returns a sorted list of unique timestamps where the engine state might change.
    (BOS candle timestamps and FVG candle 3 timestamps).
    """
    try:
        start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00")).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(end_ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")
        
    db = ClickHouseClient()
    try:
        # Fetch BOS events
        query_bos = "SELECT DISTINCT bos_candle_ts as ts FROM ihqe.bos_events WHERE bos_candle_ts >= %(start)s AND bos_candle_ts <= %(end)s"
        df_bos = db.query_df(query_bos, {"start": start_dt, "end": end_dt})
        
        # Fetch FVG events
        query_fvg = "SELECT DISTINCT ts_candle3 as ts FROM ihqe.fvg_events WHERE ts_candle3 >= %(start)s AND ts_candle3 <= %(end)s"
        df_fvg = db.query_df(query_fvg, {"start": start_dt, "end": end_dt})
        
        timestamps = set()
        if not df_bos.empty:
            timestamps.update(df_bos["ts"].astype(str).tolist())
        if not df_fvg.empty:
            timestamps.update(df_fvg["ts"].astype(str).tolist())
            
        sorted_ts = sorted(list(timestamps))
        return {"events": sorted_ts}
    finally:
        db.close()

@router.get("/state")
def get_historical_state(timestamp: str):
    """
    Reconstructs the engine state exactly as it was at the given timestamp.
    """
    try:
        as_of_ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")
        
    db = ClickHouseClient()
    try:
        checkpoint_ts = as_of_ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        chk = db.query_df("SELECT state FROM ihqe.simulation_monthly_checkpoints WHERE month = %(month)s", {"month": checkpoint_ts.date()})
        
        if chk.empty:
            # Fallback for dates before our checkpoints (or if checkpoints are missing)
            engine = MTFIntelligenceEngine()
            state = engine.run(as_of_ts=as_of_ts)
            
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
                    
            state["overlays"] = {
                "bos": bos_events,
                "fib": fib_grids,
                "fvg": fvg_events
            }
            state["cascade"] = cascade
            
            def default_serializer(obj):
                if isinstance(obj, pd.Timestamp) or isinstance(obj, datetime):
                    return obj.isoformat()
                import pydantic
                if isinstance(obj, pydantic.BaseModel):
                    return obj.model_dump()
                raise TypeError(f"Type {type(obj)} not serializable")
                
            state = json.loads(json.dumps(state, default=default_serializer))
            return state

        # If checkpoint exists, load it
        state = json.loads(chk.iloc[0]["state"])
        
        # Process delta forward (between checkpoint_ts and as_of_ts)
        delta_bos = db.query_df("SELECT * FROM ihqe.bos_events WHERE bos_candle_ts > %(start)s AND bos_candle_ts <= %(end)s AND is_active = 1 ORDER BY bos_candle_ts", {"start": checkpoint_ts, "end": as_of_ts})
        if not delta_bos.empty:
            for r in delta_bos.to_dict('records'):
                tf = r["timeframe"]
                r["bos_candle_ts"] = str(r["bos_candle_ts"]).replace(" ", "T")
                if r.get("swing_low_ts") and not pd.isna(r["swing_low_ts"]):
                    r["swing_low_ts"] = str(r["swing_low_ts"]).replace(" ", "T")
                if r.get("swing_high_ts") and not pd.isna(r["swing_high_ts"]):
                    r["swing_high_ts"] = str(r["swing_high_ts"]).replace(" ", "T")
                state["overlays"]["bos"].setdefault(tf, []).append(r)
                
        delta_fib = db.query_df("SELECT * FROM ihqe.fib_grids WHERE greatest(swing_low_ts, swing_high_ts) > %(start)s AND greatest(swing_low_ts, swing_high_ts) <= %(end)s AND is_active = 1", {"start": checkpoint_ts, "end": as_of_ts})
        if not delta_fib.empty:
            for r in delta_fib.to_dict('records'):
                tf = r["timeframe"]
                r["swing_low_ts"] = str(r["swing_low_ts"]).replace(" ", "T")
                r["swing_high_ts"] = str(r["swing_high_ts"]).replace(" ", "T")
                state["overlays"]["fib"].setdefault(tf, []).append(r)
                
        delta_fvg = db.query_df("SELECT * FROM ihqe.fvg_events WHERE ts_candle3 > %(start)s AND ts_candle3 <= %(end)s ORDER BY ts_candle3", {"start": checkpoint_ts, "end": as_of_ts})
        if not delta_fvg.empty:
            for r in delta_fvg.to_dict('records'):
                tf = r["timeframe"]
                r["ts_candle1"] = str(r["ts_candle1"]).replace(" ", "T")
                r["ts_candle2"] = str(r["ts_candle2"]).replace(" ", "T")
                r["ts_candle3"] = str(r["ts_candle3"]).replace(" ", "T")
                if r.get("ts_mitigated") and not pd.isna(r["ts_mitigated"]):
                    r["ts_mitigated"] = str(r["ts_mitigated"]).replace(" ", "T")
                    if pd.to_datetime(r["ts_mitigated"]).replace(tzinfo=None) > as_of_ts:
                        state["overlays"]["fvg"].setdefault(tf, []).append(r)
                else:
                    r["ts_mitigated"] = None
                    state["overlays"]["fvg"].setdefault(tf, []).append(r)
                    
        # Remove FVGs mitigated in the delta window
        mitigated_fvgs = db.query_df("SELECT fvg_id FROM ihqe.fvg_events WHERE ts_mitigated > %(start)s AND ts_mitigated <= %(end)s", {"start": checkpoint_ts, "end": as_of_ts})
        if not mitigated_fvgs.empty:
            mitigated_ids = set(mitigated_fvgs["fvg_id"].tolist())
            for tf in state["overlays"]["fvg"].keys():
                state["overlays"]["fvg"][tf] = [f for f in state["overlays"]["fvg"][tf] if f.get("fvg_id") not in mitigated_ids]
                
        # Update cascade state for as_of_ts
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
        state["cascade"] = cascade
        
        # Recalculate biases using merged state
        engine = MTFIntelligenceEngine()
        price_state = engine.get_current_price(db, as_of_ts)
        current_price = price_state.mid if price_state else 0.0
        
        biases = {}
        for tf in engine.timeframes:
            tf_bos = state["overlays"]["bos"].get(tf, [])
            tf_fib = state["overlays"]["fib"].get(tf, [])
            tf_fvg = state["overlays"]["fvg"].get(tf, [])
            
            bias = 0
            if tf_bos:
                latest_bos = tf_bos[-1]
                bos_dir = latest_bos["direction"].lower()
                is_bullish = "bullish" in bos_dir or "long" in bos_dir
                
                if not tf_fib:
                    bias = 1 if is_bullish else -1
                else:
                    level_0_5 = tf_fib[-1].get("level_0_500", 0.0)
                    if level_0_5 == 0.0:
                        bias = 1 if is_bullish else -1
                    else:
                        if is_bullish:
                            if current_price < level_0_5:
                                unmit = [f for f in tf_fvg if f["direction"].lower() == "bullish"]
                                bias = 2 if unmit else 1
                            else:
                                bias = 1
                        else:
                            if current_price > level_0_5:
                                unmit = [f for f in tf_fvg if f["direction"].lower() == "bearish"]
                                bias = -2 if unmit else -1
                            else:
                                bias = -1
            biases[tf] = bias
            
        state["tf_bias"] = biases
        state["composite_score"] = engine.calculate_composite(biases)
        state["price"] = price_state.model_dump() if price_state else None
        
        return state
    finally:
        db.close()

@router.websocket("/stream")
async def stream_candles(websocket: WebSocket):
    """
    WebSocket endpoint for batch streaming candles.
    Expects initial message: {start_ts, end_ts, timeframe, speed}
    """
    await websocket.accept()
    db = ClickHouseClient()
    try:
        data = await websocket.receive_text()
        params = json.loads(data)
        
        start_str = params.get("start_ts")
        end_str = params.get("end_ts")
        timeframe = params.get("timeframe")
        
        if not all([start_str, end_str, timeframe]):
            await websocket.send_text(json.dumps({"error": "Missing parameters"}))
            return
            
        try:
            start_ts = datetime.fromisoformat(start_str.replace("Z", "+00:00")).replace(tzinfo=None)
            end_ts = datetime.fromisoformat(end_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            await websocket.send_text(json.dumps({"error": "Invalid timestamp format"}))
            return
            
        # We will stream in chunks to avoid blowing up memory
        # First get total count
        count_query = "SELECT count(*) as c FROM ihqe.xauusd_ohlcv WHERE timeframe = %(tf)s AND ts >= %(start)s AND ts <= %(end)s"
        count_res = db.query_df(count_query, {"tf": timeframe, "start": start_ts, "end": end_ts})
        total_rows = int(count_res.iloc[0]["c"]) if not count_res.empty else 0
        
        CHUNK_SIZE = 100
        offset = 0
        
        while offset < total_rows:
            query = f"""
            SELECT ts, open, high, low, close, tick_count
            FROM ihqe.xauusd_ohlcv 
            WHERE timeframe = %(tf)s AND ts >= %(start)s AND ts <= %(end)s
            ORDER BY ts ASC
            LIMIT {CHUNK_SIZE} OFFSET {offset}
            """
            chunk_df = db.query_df(query, {"tf": timeframe, "start": start_ts, "end": end_ts})
            if chunk_df.empty:
                break
                
            chunk_df["ts"] = chunk_df["ts"].astype(str)
            records = chunk_df.to_dict("records")
            
            await websocket.send_text(json.dumps({"type": "chunk", "data": records}))
            
            # Wait for client acknowledgement before sending next chunk to avoid flooding
            ack = await websocket.receive_text()
            if ack != "next":
                break
                
            offset += CHUNK_SIZE
            
        await websocket.send_text(json.dumps({"type": "done"}))
        
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_text(json.dumps({"error": str(e)}))
    finally:
        db.close()
