"""
IHQE v3 — Signal Classification Engine

Classifies and publishes signals for both swing and scalp layers.

Swing signal hierarchy:
    0 gates → None
    1 gate  → 'macro_alert'   (12M BOS confirmed)
    2 gates → 'mid_alert'     (12M zone entered + 3M FVG confirmed)
    3 gates → 'active'        (all 3 gates confirmed)
    3 gates + price in 1M zone → 'execute'

Scalp signals:
    Only published when swing gates_confirmed >= 2
    Types: 'scalp_path' | 'scalp_cont'
"""

import logging
import os
import sys
import uuid
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import settings

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    Classifies and publishes signals for both swing and scalp layers.
    """

    def classify_swing(
        self, gates_confirmed: int, price_in_1m_zone: bool = False, is_12m_aligned: bool = False
    ) -> Optional[str]:
        """
        Classify a swing signal based on gate count and zone status.

        Args:
            gates_confirmed: Number of confirmed gates for 3M cascade (0-2)
            price_in_1m_zone: Whether price is inside the 1M discount/premium zone
            is_12m_aligned: Whether the 12M macro gate is also aligned

        Returns:
            Signal type string or None
        """
        if price_in_1m_zone and gates_confirmed == 2:
            return "execute"

        levels = {
            0: None,
            1: "mid_alert",      # 3M BOS confirmed
            2: "active",         # 3M BOS + 1M FVG confirmed
        }
        
        base_signal = levels.get(gates_confirmed)
        
        # Upgrade Mid or Active if 12M is aligned
        if base_signal in ["mid_alert", "active"] and is_12m_aligned:
            return "strong_long" if base_signal == "active" else "strong_alert"
            
        return base_signal

    def classify_scalp(
        self, scalp_type: str, gates_confirmed: int
    ) -> Optional[str]:
        """
        Scalp signals only published when swing gates_confirmed >= 2.

        Args:
            scalp_type: 'path' | 'continuation'
            gates_confirmed: Number of confirmed swing gates

        Returns:
            Scalp signal type string or None
        """
        if gates_confirmed < 2:
            return None

        if scalp_type == "path":
            return "scalp_path"
        elif scalp_type == "continuation":
            return "scalp_cont"
        return None

    def generate_signals(self, cascade_results: dict) -> list[dict]:
        """
        Generate trade signals from cascade results.

        Args:
            cascade_results: Output from run_full_cascade()

        Returns:
            List of signal dicts ready for database insertion
        """
        signals = []

        print(f"\n{'='*60}")
        print(f"  IHQE v3 Signal Engine")
        print(f"{'='*60}\n")

        for direction in ["bullish", "bearish"]:
            dir_results = cascade_results.get(direction, {})
            swing_results = dir_results.get("swing", {})
            scalp_results = dir_results.get("scalp", [])
            gates_confirmed = dir_results.get("gates_confirmed", 0)
            entry_valid = dir_results.get("entry_valid", False)
            is_12m_aligned = dir_results.get("12m_aligned", False)

            # ── Swing Signal ──────────────────────────────────────────
            signal_type = self.classify_swing(gates_confirmed, entry_valid, is_12m_aligned)
            if signal_type:
                trade_direction = "long" if direction == "bullish" else "short"

                # Get target zone from the most refined grid
                grids = swing_results.get("grids", {})
                target_upper = 0.0
                target_lower = 0.0

                # For swing: use the 1M grid zone if available, else 3M, else 12M
                for tf in reversed(["12M", "3M", "1M"]):
                    tf_grids = grids.get(tf, [])
                    if tf_grids:
                        grid = tf_grids[0]
                        if direction == "bullish":
                            target_upper = grid["level_0_500"]
                            target_lower = grid["level_0_618"]
                        else:
                            target_upper = grid["level_0_382"]
                            target_lower = grid["level_0_500"]
                        break

                signal = {
                    "signal_id": str(uuid.uuid4()),
                    "signal_type": signal_type,
                    "trade_type": "swing",
                    "direction": trade_direction,
                    "gates_confirmed": gates_confirmed,
                    "target_upper": target_upper,
                    "target_lower": target_lower,
                    "linked_signal_id": None,
                    "published_at": datetime.utcnow(),
                    "status": "open",
                }
                signals.append(signal)

                if signal_type == "execute":
                    from alerts.telegram_bot import send_telegram_alert
                    # Calculate dummy R:R for now since we just have a zone
                    # Assuming target_upper and target_lower are TP and SL depending on direction
                    tp = target_upper if trade_direction == "bullish" else target_lower
                    sl = target_lower if trade_direction == "bullish" else target_upper
                    entry = (tp + sl) / 2
                    try:
                        ratio = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
                    except ZeroDivisionError:
                        ratio = 0.0
                    msg = (
                        f"🚨 IHQE — EXECUTE SIGNAL | Direction: {trade_direction} | "
                        f"Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | R:R: {ratio:.2f}"
                    )
                    send_telegram_alert(f"execute_{trade_direction}", msg)

                print(f"  {signal_type.upper():>12s} | {trade_direction:>5s} | "
                      f"Gates: {gates_confirmed}/3 | "
                      f"Zone: ${target_lower:.2f} - ${target_upper:.2f}")
                    
                # Handle Telegram Alerts for Upgraded Signals
                if signal_type in ["strong_long", "strong_alert"]:
                    from alerts.telegram_bot import send_telegram_alert
                    import asyncio
                    
                    trade_str = "STRONG LONG" if trade_direction == "long" else "STRONG SHORT"
                    base_str = "Active" if signal_type == "strong_long" else "Mid"
                    # Default composite score to 0 for now since engine might not provide it directly here
                    composite = 0
                    
                    msg = f"📈 IHQE — Signal Upgraded | 3M setup → {trade_str} | Upgraded by: 12M gate alignment | Score: {composite}"
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(send_telegram_alert(msg))
                    except RuntimeError:
                        asyncio.run(send_telegram_alert(msg))

            # ── Scalp Signals ──────────────────────────────────────────
            macro_bias = cascade_results.get("12m_macro_bias", 0)
            for scalp in scalp_results:
                trade_direction = scalp["direction"]
                trade_dir_long = "long" if trade_direction == "bullish" else "short"
                
                # Apply 12M Macro Direction Filter
                if macro_bias == 1 and trade_dir_long == "short":
                    continue
                if macro_bias == -1 and trade_dir_long == "long":
                    continue
                
                scalp_type = scalp.get("scalp_type", "")
                scalp_signal = {
                    "signal_id": str(uuid.uuid4()),
                    "signal_type": scalp_type,
                    "trade_type": scalp_type,
                    "direction": trade_direction,
                    "gates_confirmed": gates_confirmed,
                    "target_upper": scalp["entry_price"],
                    "target_lower": scalp["stop_loss"],
                    "linked_signal_id": None,
                    "published_at": datetime.utcnow(),
                    "status": "open",
                }
                signals.append(scalp_signal)

                print(f"  {scalp_type.upper():>12s} | {scalp['direction']:>5s} | "
                      f"{scalp['timeframe']} | "
                      f"Entry: ${scalp['entry_price']:.2f} "
                      f"SL: ${scalp['stop_loss']:.2f} "
                      f"TP: ${scalp['take_profit']:.2f}")

        if not signals:
            print(f"  No publishable signals at this time")

        print(f"\n  Total signals: {len(signals)}")
        print(f"{'='*60}")

        return signals


def run_signal_engine(db_client) -> list[dict]:
    """Full signal engine pipeline:
    
    Pass 1: Independent structure detection on ALL timeframes
            (populates chart overlays — BOS, Fib, FVG for every chart)
    Pass 2: Cascade signal generation
            (processes the gated 12M→3M→1M cascade for trade signals)
    
    Returns list of generated signals.
    """
    from engine.structure_detector import StructureDetector
    from engine.cascade import run_full_cascade

    # ── Pass 1: Detect structure on all timeframes ──────────────────
    structure = StructureDetector(db_client)
    structure.detect_all_timeframes(incremental=True)

    # ── Pass 2: Run cascade for signal generation ────────────────────
    cascade_results = run_full_cascade(db_client)

    # Generate signals from cascade results
    engine = SignalEngine()
    signals = engine.generate_signals(cascade_results)

    # Store signals in database
    if signals:
        db_client.clear_trade_signals()
        db_client.insert_trade_signals(signals)

    return signals


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    from database.clickhouse_client import ClickHouseClient
    db = ClickHouseClient()
    signals = run_signal_engine(db)
    db.close()
