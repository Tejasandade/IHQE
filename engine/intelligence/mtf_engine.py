import os
import sys
import json
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
import logging
from pydantic import ValidationError

# Ensure we can import from top level
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from database.clickhouse_client import ClickHouseClient
from config.settings import INTELLIGENCE_WEIGHTS
from api.auth.database import SessionLocal
from api.models import Signal
from engine.models import BosEvent, FibGrid, FvgEvent, PriceState

logger = logging.getLogger(__name__)

class MTFIntelligenceEngine:
    def __init__(self):
        self.timeframes = ['12M', '3M', '1M', '4H', '1H']
        
    def get_current_price(self, db: ClickHouseClient, as_of_ts: Optional[datetime] = None) -> Optional[PriceState]:
        """Fetch the most recent mid price from xauusd_ticks."""
        where_clause = ""
        params = {}
        if as_of_ts:
            where_clause = "WHERE ts <= %(as_of_ts)s"
            params["as_of_ts"] = as_of_ts
            
        query = f"""
        SELECT (bid + ask) / 2 AS mid, bid, ask, ts AS timestamp
        FROM ihqe.xauusd_ticks 
        {where_clause}
        ORDER BY ts DESC 
        LIMIT 1
        """
        result = db.query_df(query, params)
        if result.empty:
            return None
        try:
            return PriceState.model_validate(result.iloc[0].to_dict())
        except ValidationError as e:
            logger.error(f"PriceState ValidationError: {e}")
            return None

    def calculate_tf_bias(self, timeframe: str, current_price: float, db: ClickHouseClient, as_of_ts: Optional[datetime] = None) -> int:
        """
        Calculate bias (-2 to +2) for a given timeframe based on ClickHouse state.
        """
        # 1. Check for active confirmed BOS
        bos_df = db.get_bos_events(timeframe, active_only=True, as_of_ts=as_of_ts)
        if bos_df.empty:
            return 0
        
        try:
            latest_bos = BosEvent.model_validate(bos_df.iloc[-1].to_dict())
        except ValidationError as e:
            logger.error(f"BosEvent ValidationError for {timeframe}: {e}")
            return 0
            
        bos_dir = latest_bos.direction.lower()
        if not bos_dir:
            return 0
            
        is_bullish = "bullish" in bos_dir or "long" in bos_dir
        
        # 2. Get active Fib Grid to find 0.5 level
        fib_df = db.get_fib_grids(timeframe, active_only=True, as_of_ts=as_of_ts)
        if fib_df.empty:
            return 1 if is_bullish else -1
            
        try:
            latest_grid = FibGrid.model_validate(fib_df.iloc[-1].to_dict())
        except ValidationError as e:
            logger.error(f"FibGrid ValidationError for {timeframe}: {e}")
            return 0
            
        level_0_5 = latest_grid.level_0_500
        
        if level_0_5 == 0.0:
            return 1 if is_bullish else -1
            
        # 3. Get FVGs
        fvg_df = db.get_fvg_events(timeframe, as_of_ts=as_of_ts)
        valid_fvgs = []
        for r in fvg_df.to_dict('records'):
            try:
                valid_fvgs.append(FvgEvent.model_validate(r))
            except ValidationError as e:
                logger.error(f"FvgEvent ValidationError for {timeframe}: {e}")
                
        if is_bullish:
            if current_price < level_0_5:
                unmit_bullish = [f for f in valid_fvgs if f.direction.lower() == 'bullish' and not f.is_mitigated]
                if unmit_bullish:
                    return 2
                return 1
            else:
                return 1
        else:
            if current_price > level_0_5:
                unmit_bearish = [f for f in valid_fvgs if f.direction.lower() == 'bearish' and not f.is_mitigated]
                if unmit_bearish:
                    return -2
                return -1
            else:
                return -1

    def calculate_composite(self, biases: Dict[str, int]) -> float:
        """Calculate weighted composite score."""
        score = 0.0
        for tf, bias in biases.items():
            weight = INTELLIGENCE_WEIGHTS.get(tf, 0.0)
            score += bias * weight
        return score

    def evaluate_signals(self, composite_score: float, biases: Dict[str, int], current_price: float = 0.0):
        """Evaluate thresholds and conflict rule, and store in PostgreSQL if necessary."""
        signal_type = None
        
        # Thresholds
        if composite_score >= 20.0:
            signal_type = "Strong Long"
        elif composite_score >= 10.0:
            signal_type = "Moderate Long"
        elif composite_score <= -20.0:
            signal_type = "Strong Short"
        elif composite_score <= -10.0:
            signal_type = "Moderate Short"
            
        # Conflict Detection (Path Scalp)
        bias_12m = biases.get('12M', 0)
        bias_3m = biases.get('3M', 0)
        
        path_scalp = False
        if bias_12m != 0 and bias_3m != 0:
            # Using bitwise sign extraction or simple > 0 check
            sign_12m = 1 if bias_12m > 0 else -1
            sign_3m = 1 if bias_3m > 0 else -1
            if sign_12m != sign_3m:
                path_scalp = True
                
        # If Path Scalp is true, emit a Path Scalp signal (it can coincide with composite score signals,
        # but the spec says "If true, flag a Path Scalp opportunity regardless of composite score").
        # We will emit two signals if both conditions are met, or just one combined.
        # It's cleaner to store them as separate rows or combine them. We'll store separate.
        
        events_to_store = []
        
        from alerts.telegram_bot import send_telegram_alert
        
        if signal_type:
            events_to_store.append((signal_type, composite_score))
            msg = (
                f"📊 IHQE — Score Alert | Score: {composite_score} ({signal_type}) | "
                f"12M: {biases.get('12M', 0)} | 3M: {biases.get('3M', 0)} | "
                f"1M: {biases.get('1M', 0)} | 4H: {biases.get('4H', 0)} | 1H: {biases.get('1H', 0)}"
            )
            send_telegram_alert(f"score_{signal_type}", msg)
            
        if path_scalp:
            events_to_store.append(("Path Scalp", composite_score))
            msg = (
                f"⚡ IHQE — Path Scalp | 12M: {bias_12m} vs 3M: {bias_3m} | "
                f"Counter-trend opportunity | Current price: {current_price}"
            )
            send_telegram_alert("path_scalp", msg)
            
        if events_to_store:
            self._store_signals(events_to_store, biases)
            
    def _store_signals(self, events: list[Tuple[str, float]], biases: Dict[str, int]):
        """Store generated signals in PostgreSQL."""
        db = SessionLocal()
        try:
            for s_type, score in events:
                signal = Signal(
                    signal_type=s_type,
                    composite_score=score,
                    metadata_json=biases
                )
                db.add(signal)
            db.commit()
        except Exception as e:
            print(f"Failed to store signal: {e}")
            db.rollback()
        finally:
            db.close()

    def run(self, as_of_ts: Optional[datetime] = None) -> Dict[str, Any]:
        """Main execution method."""
        db = ClickHouseClient()
        try:
            current_price_state = self.get_current_price(db, as_of_ts=as_of_ts)
            if not current_price_state:
                # No ticks available
                return {"composite_score": 0.0, "biases": {tf: 0 for tf in self.timeframes}, "path_scalp": False}
            
            current_price = current_price_state.mid
            
            biases = {}
            for tf in self.timeframes:
                biases[tf] = self.calculate_tf_bias(tf, current_price, db, as_of_ts=as_of_ts)
                
            composite = self.calculate_composite(biases)
            
            # evaluate and possibly store
            self.evaluate_signals(composite, biases, current_price)
            
            bias_12m = biases.get('12M', 0)
            bias_3m = biases.get('3M', 0)
            path_scalp = (bias_12m != 0 and bias_3m != 0 and (bias_12m * bias_3m) < 0)
            
            return {
                "composite_score": composite,
                "biases": biases,
                "path_scalp": path_scalp,
                "timestamp": datetime.utcnow().isoformat()
            }
        finally:
            db.close()

# Global instance
mtf_engine = MTFIntelligenceEngine()

def run_intelligence_engine():
    """Trigger function to run the MTF Engine."""
    return mtf_engine.run()
