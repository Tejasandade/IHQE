"""
IHQE v3 — Break of Structure (BOS) Detector

The gatekeeper of the entire system.
No BOS on 12-Month = nothing happens. Full stop.

BOS DEFINITION (Bullish):
    A candle CLOSES above the most recent significant swing high.
    Swing highs are detected using Williams Fractals (5-bar or 7-bar).
    A minimum size filter is applied: the close must exceed the broken level
    by a minimum percentage specific to the timeframe.

BOS DEFINITION (Bearish):
    A candle CLOSES below the most recent significant swing low.
    Swing lows are detected using Williams Fractals (5-bar or 7-bar).
    A minimum size filter is applied.

After BOS is confirmed, Fibonacci swing points are determined:
    Bullish BOS → Point A = lowest low of the leg preceding BOS
                  Point B = highest high after the BOS candle closes
    Bearish BOS → Point A = highest high of the leg preceding BOS
                  Point B = lowest low after the BOS candle closes
"""

import logging
import os
import sys
import uuid
from typing import Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logger = logging.getLogger(__name__)

from config import settings


class BOSDetector:
    """
    Detects Break of Structure on a given timeframe using Williams Fractals.
    """

    def detect(self, candles: pd.DataFrame, timeframe: str) -> list[dict]:
        """
        Scans candles and returns all BOS events.
        """
        if len(candles) < 7:
            return []

        bos_events = []
        ts_index = candles.index.tolist()
        highs = candles["high"].values.astype(float)
        lows = candles["low"].values.astype(float)
        closes = candles["close"].values.astype(float)
        times = candles.index
        n = len(candles)

        # 1. Pre-calculate Swing Highs and Lows (Williams Fractals)
        side = settings.BOS_FRACTAL_SIDE.get(timeframe, settings.BOS_FRACTAL_SIDE.get("default", 2))
        
        is_swing_high = np.zeros(n, dtype=bool)
        is_swing_low = np.zeros(n, dtype=bool)

        for i in range(side, n - side):
            # Bullish swing high: strictly greater than surrounding
            window_highs = np.concatenate([highs[i-side:i], highs[i+1:i+side+1]])
            if highs[i] > np.max(window_highs):
                is_swing_high[i] = True
                
            # Bearish swing low: strictly lower than surrounding
            window_lows = np.concatenate([lows[i-side:i], lows[i+1:i+side+1]])
            if lows[i] < np.min(window_lows):
                is_swing_low[i] = True

        # Track the most recent confirmed swing high/low at any given bar
        # A swing at index k is confirmed at bar k + side
        latest_swing_high_idx = -1
        latest_swing_low_idx = -1
        
        threshold_pct = settings.BOS_PCT_THRESHOLDS.get(timeframe, 1.0)

        # To handle deduplication
        last_broken_swing_high_idx = -1
        last_broken_swing_low_idx = -1

        for i in range(side + 1, n):
            current_close = closes[i]
            current_ts = ts_index[i]

            # Update confirmed swings
            # A swing at (i - side) is now confirmed because we are at i
            check_idx = i - side
            if is_swing_high[check_idx]:
                latest_swing_high_idx = check_idx
            if is_swing_low[check_idx]:
                latest_swing_low_idx = check_idx

            # ── BULLISH BOS ──────────────────────────────────────────
            if latest_swing_high_idx != -1 and latest_swing_high_idx != last_broken_swing_high_idx:
                broken_level = highs[latest_swing_high_idx]
                if current_close > broken_level:
                    # Size filter
                    pct_diff = abs(current_close - broken_level) / broken_level * 100
                    if pct_diff >= threshold_pct:
                        last_broken_swing_high_idx = latest_swing_high_idx
                        
                        # Find Point A: lowest low of the leg preceding the broken swing high
                        # Leg goes from some lookback up to the swing high index
                        leg_start = max(0, latest_swing_high_idx - settings.BOS_SWING_LEG_LOOKBACK)
                        leg_lows = lows[leg_start:latest_swing_high_idx+1]
                        
                        if len(leg_lows) > 0:
                            swing_low = float(np.min(leg_lows))
                            swing_low_idx = leg_start + int(np.argmin(leg_lows))
                        else:
                            swing_low = lows[latest_swing_high_idx]
                            swing_low_idx = latest_swing_high_idx
                        swing_low_ts = times[swing_low_idx]

                        # Find Point B: highest high after BOS candle (forward scan)
                        fwd_end = min(n, i + settings.BOS_SWING_FORWARD_SCAN + 1)
                        fwd_highs = highs[i:fwd_end]
                        swing_high = float(np.max(fwd_highs))
                        swing_high_idx = i + int(np.argmax(fwd_highs))
                        swing_high_ts = times[swing_high_idx]

                        bos_events.append({
                            "bos_id": str(uuid.uuid4()),
                            "timeframe": timeframe,
                            "direction": "bullish",
                            "bos_candle_ts": current_ts,
                            "broken_level": broken_level,
                            "bos_close": current_close,
                            "swing_low": swing_low,
                            "swing_low_ts": swing_low_ts,
                            "swing_high": swing_high,
                            "swing_high_ts": swing_high_ts,
                            "is_active": 1,
                        })

            # ── BEARISH BOS ──────────────────────────────────────────
            if latest_swing_low_idx != -1 and latest_swing_low_idx != last_broken_swing_low_idx:
                broken_level = lows[latest_swing_low_idx]
                if current_close < broken_level:
                    # Size filter
                    pct_diff = abs(current_close - broken_level) / broken_level * 100
                    if pct_diff >= threshold_pct:
                        last_broken_swing_low_idx = latest_swing_low_idx
                        
                        # Find Point A: highest high of the leg preceding the broken swing low
                        leg_start = max(0, latest_swing_low_idx - settings.BOS_SWING_LEG_LOOKBACK)
                        leg_highs = highs[leg_start:latest_swing_low_idx+1]
                        
                        if len(leg_highs) > 0:
                            swing_high = float(np.max(leg_highs))
                            swing_high_idx = leg_start + int(np.argmax(leg_highs))
                        else:
                            swing_high = highs[latest_swing_low_idx]
                            swing_high_idx = latest_swing_low_idx
                        swing_high_ts = times[swing_high_idx]

                        # Find Point B: lowest low after BOS candle (forward scan)
                        fwd_end = min(n, i + settings.BOS_SWING_FORWARD_SCAN + 1)
                        fwd_lows = lows[i:fwd_end]
                        swing_low = float(np.min(fwd_lows))
                        swing_low_idx = i + int(np.argmin(fwd_lows))
                        swing_low_ts = times[swing_low_idx]

                        bos_events.append({
                            "bos_id": str(uuid.uuid4()),
                            "timeframe": timeframe,
                            "direction": "bearish",
                            "bos_candle_ts": current_ts,
                            "broken_level": broken_level,
                            "bos_close": current_close,
                            "swing_high": swing_high,
                            "swing_high_ts": swing_high_ts,
                            "swing_low": swing_low,
                            "swing_low_ts": swing_low_ts,
                            "is_active": 1,
                        })

        self._check_invalidation(bos_events, candles)
        return bos_events

    def _check_invalidation(
        self, bos_events: list[dict], candles: pd.DataFrame
    ) -> None:
        """
        Invalidate BOS events where price has subsequently closed
        beyond the protective swing level.

        Bullish BOS: invalidated if any subsequent candle closes below swing_low
        Bearish BOS: invalidated if any subsequent candle closes above swing_high
        """
        if not bos_events or candles.empty:
            return

        closes = candles["close"].values.astype(float)
        ts_array = candles.index.values

        for bos in bos_events:
            bos_ts = pd.Timestamp(bos["bos_candle_ts"])
            start_idx = np.searchsorted(ts_array, bos_ts.asm8, side="right")
            if start_idx >= len(closes):
                continue

            post_closes = closes[start_idx:]

            if bos["direction"] == "bullish":
                if np.any(post_closes < bos["swing_low"]):
                    bos["is_active"] = 0
            elif bos["direction"] == "bearish":
                if np.any(post_closes > bos["swing_high"]):
                    bos["is_active"] = 0

    def get_active_bos(
        self, bos_events: list[dict], timeframe: str,
        direction: Optional[str] = None
    ) -> Optional[dict]:
        """
        Returns the most recent unbroken (active) BOS event
        for the given timeframe and optional direction.
        """
        filtered = [
            b for b in bos_events
            if b["timeframe"] == timeframe
            and b["is_active"] == 1
            and (direction is None or b["direction"] == direction)
        ]

        if not filtered:
            return None

        # Return the most recent by timestamp
        return max(filtered, key=lambda b: b["bos_candle_ts"])

    def get_most_recent_bos(
        self, bos_events: list[dict], timeframe: str,
        direction: Optional[str] = None
    ) -> Optional[dict]:
        """
        Returns the most recent BOS event regardless of active status.
        Useful for historical analysis.
        """
        filtered = [
            b for b in bos_events
            if b["timeframe"] == timeframe
            and (direction is None or b["direction"] == direction)
        ]

        if not filtered:
            return None

        return max(filtered, key=lambda b: b["bos_candle_ts"])


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    from database.clickhouse_client import ClickHouseClient

    db = ClickHouseClient()
    detector = BOSDetector()

    # Scan 12M chart for BOS events
    candles = db.get_ohlcv("12M")
    if not candles.empty:
        events = detector.detect(candles, "12M")
        print(f"\n12M BOS Events: {len(events)}")
        for e in events:
            status = "ACTIVE" if e["is_active"] else "BROKEN"
            print(f"  {e['direction'].upper():>7s} | {e['bos_candle_ts']} | "
                  f"Broken: {e['broken_level']:.2f} | "
                  f"Close: {e['bos_close']:.2f} | "
                  f"Swing: {e['swing_low']:.2f}-{e['swing_high']:.2f} | "
                  f"{status}")

        # Store in DB
        db.clear_bos_events("12M")
        db.insert_bos_events(events)

        # Get active BOS
        active = detector.get_active_bos(events, "12M", "bullish")
        if active:
            print(f"\nActive Bullish BOS: {active['bos_candle_ts']} | "
                  f"Swing: {active['swing_low']:.2f}-{active['swing_high']:.2f}")

    db.close()
