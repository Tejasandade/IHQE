import os
import sys
import json
from datetime import datetime
from typing import Dict, Any, Tuple

# Ensure we can import from top level
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from database.clickhouse_client import ClickHouseClient
from config.settings import INTELLIGENCE_WEIGHTS
from api.auth.database import SessionLocal
from api.models import Signal

class MTFIntelligenceEngine:
    def __init__(self):
        self.timeframes = ['12M', '3M', '1M', '4H', '1H']
        
    def get_current_price(self, db: ClickHouseClient) -> float:
        """Fetch the most recent mid price from xauusd_ticks."""
        query = """
        SELECT (bid + ask) / 2 AS mid_price 
        FROM ihqe.xauusd_ticks 
        ORDER BY ts DESC 
        LIMIT 1
        """
        result = db.query_df(query)
        if result.empty:
            return 0.0
        return float(result.iloc[0]['mid_price'])

    def calculate_tf_bias(self, timeframe: str, current_price: float, db: ClickHouseClient) -> int:
        """
        Calculate bias (-2 to +2) for a given timeframe based on ClickHouse state.
        """
        # 1. Check for active confirmed BOS
        bos_df = db.get_bos_events(timeframe, active_only=True)
        if bos_df.empty:
            return 0
        
        # Get the most recent active BOS
        latest_bos = bos_df.iloc[-1]
        bos_dir = latest_bos.get("direction", "").lower()
        if not bos_dir:
            return 0
            
        is_bullish = "bullish" in bos_dir or "long" in bos_dir
        
        # 2. Get active Fib Grid to find 0.5 level
        fib_df = db.get_fib_grids(timeframe, active_only=True)
        if fib_df.empty:
            # If no active grid, we default to +1 or -1 based on BOS direction
            return 1 if is_bullish else -1
            
        latest_grid = fib_df.iloc[-1]
        level_0_5 = latest_grid.get("level_0_500", 0.0)
        
        if level_0_5 == 0.0:
            return 1 if is_bullish else -1
            
        # 3. Get FVGs
        fvg_df = db.get_fvg_events(timeframe)
        
        if is_bullish:
            if current_price < level_0_5:
                # Need unmitigated bullish FVG in the zone
                if not fvg_df.empty:
                    # Filter for active bullish FVGs
                    unmit_bullish = fvg_df[(fvg_df['direction'] == 'bullish') & (fvg_df['is_mitigated'] == False)]
                    if not unmit_bullish.empty:
                        return 2
                return 1
            else:
                return 1
        else:
            if current_price > level_0_5:
                # Need unmitigated bearish FVG in the zone
                if not fvg_df.empty:
                    unmit_bearish = fvg_df[(fvg_df['direction'] == 'bearish') & (fvg_df['is_mitigated'] == False)]
                    if not unmit_bearish.empty:
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

    def evaluate_signals(self, composite_score: float, biases: Dict[str, int]):
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
        if signal_type:
            events_to_store.append((signal_type, composite_score))
        if path_scalp:
            events_to_store.append(("Path Scalp", composite_score))
            
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

    def run(self) -> Dict[str, Any]:
        """Main execution method."""
        db = ClickHouseClient()
        try:
            current_price = self.get_current_price(db)
            if current_price == 0.0:
                # No ticks available
                return {"composite_score": 0.0, "biases": {tf: 0 for tf in self.timeframes}, "path_scalp": False}
                
            biases = {}
            for tf in self.timeframes:
                biases[tf] = self.calculate_tf_bias(tf, current_price, db)
                
            composite = self.calculate_composite(biases)
            
            # evaluate and possibly store
            self.evaluate_signals(composite, biases)
            
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
