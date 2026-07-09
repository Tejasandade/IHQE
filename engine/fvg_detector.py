"""
IHQE v3 — Fair Value Gap (FVG) Detector

Detects FVGs ONLY inside active discount/premium zones.
Must receive the active Fibonacci grid for context.

Only valid on:
    - 3-Month and 1-Month timeframes for swing trades
    - 4-Hour and 1-Hour for scalp trades

The 12-Month uses BOS, NOT FVG. Never run FVG detection on 12M.

FVG DEFINITION (Bullish, for discount zone):
    3 consecutive candles where:
        candle[2].low > candle[0].high
    Gap top    = candle[2].low
    Gap bottom = candle[0].high
    Wick rule: candle[1].low must NOT go below candle[0].low
    Any gap size qualifies (even 1 tick)
    Use the FIRST FVG that forms (Extreme FVG) — ignore subsequent ones

FVG DEFINITION (Bearish, for premium zone):
    3 consecutive candles where:
        candle[2].high < candle[0].low
    Gap top    = candle[0].low
    Gap bottom = candle[2].high
    Wick rule: candle[1].high must NOT go above candle[0].high
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


class FVGDetector:
    """
    Detects FVGs ONLY inside active discount/premium zones.
    Must receive the active Fibonacci grid for context.
    Only valid on 3-Month and 1-Month timeframes for swing trades.
    Valid on 4H and 1H for scalp trades.
    """

    def detect_in_zone(
        self,
        candles: pd.DataFrame,
        timeframe: str,
        zone_upper: float,
        zone_lower: float,
        direction: str,
        parent_fvg_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Scans for FVGs where the FVG itself is located
        INSIDE the zone boundaries [zone_lower, zone_upper].

        For bullish: only flag FVGs where gap_bottom >= zone_lower
                     and gap_top <= zone_upper
        For bearish: only flag FVGs where gap_top <= zone_upper
                     and gap_bottom >= zone_lower

        Returns only the FIRST qualifying FVG (Extreme FVG).
        Subsequent FVGs in the same zone are stored but is_extreme = 0.

        Args:
            candles: OHLCV DataFrame indexed by timestamp
            timeframe: Canonical timeframe key
            zone_upper: Upper boundary of the zone (e.g., 0.5 level)
            zone_lower: Lower boundary of the zone (e.g., swing low / 0.0 level)
            direction: 'bullish' or 'bearish'
            parent_fvg_id: Optional ID of the parent FVG for linking

        Returns:
            List of FVG dicts found within the zone. First one has is_extreme=1.
        """
        if len(candles) < 3:
            return []

        all_fvgs = self._detect_raw(candles, timeframe, direction)

        # Filter to only FVGs inside the zone
        zone_fvgs = []
        found_extreme = False

        for fvg in all_fvgs:
            in_zone = self._is_fvg_in_zone(
                fvg, zone_upper, zone_lower, direction
            )
            
            if not in_zone:
                # TEMPORARY DEBUG LOGGING FOR REJECTIONS
                gap_top = fvg["gap_top"]
                gap_bottom = fvg["gap_bottom"]
                
                dist_upper = max(0, gap_bottom - zone_upper) if direction == 'bullish' else max(0, gap_top - zone_upper)
                dist_lower = max(0, zone_lower - gap_top) if direction == 'bullish' else max(0, zone_lower - gap_bottom)
                
                # A more precise absolute distance from the boundaries
                if direction == 'bullish':
                    dist = min(abs(gap_bottom - zone_lower), abs(gap_top - zone_upper))
                else:
                    dist = min(abs(gap_top - zone_upper), abs(gap_bottom - zone_lower))
                    
                logger.info(f"REJECTED FVG ({direction}) | Gap: [{gap_bottom:.2f} - {gap_top:.2f}] | Zone: [{zone_lower:.2f} - {zone_upper:.2f}] | Missed zone by approx ${dist:.2f}")

            if in_zone:
                fvg["parent_fvg_id"] = parent_fvg_id

                if not found_extreme:
                    fvg["is_extreme"] = 1
                    found_extreme = True
                else:
                    fvg["is_extreme"] = 0

                zone_fvgs.append(fvg)

        return zone_fvgs

    def _is_fvg_in_zone(
        self,
        fvg: dict,
        zone_upper: float,
        zone_lower: float,
        direction: str,
    ) -> bool:
        """
        Check if an FVG falls within the given zone boundaries.

        For bullish (discount zone): gap must be between zone_lower and zone_upper
        For bearish (premium zone): gap must be between zone_lower and zone_upper
        """
        gap_top = fvg["gap_top"]
        gap_bottom = fvg["gap_bottom"]

        # Add a 0.3% proximity buffer for optimal performance
        buffer = zone_upper * 0.003

        if direction == "bullish":
            # FVG should be in the discount area (below zone_upper)
            return gap_bottom >= (zone_lower - buffer) and gap_top <= (zone_upper + buffer)
        elif direction == "bearish":
            # FVG should be in the premium area (above zone_lower)
            return gap_bottom >= (zone_lower - buffer) and gap_top <= (zone_upper + buffer)
        return False

    def filter_fvg_dataframe(
        self,
        df: pd.DataFrame,
        zone_lower: float,
        zone_upper: float,
        direction: str,
        buffer_pct: float = 0.005,
    ) -> pd.DataFrame:
        """
        Vectorized filter applying the exact same logic as _is_fvg_in_zone.
        Expects a DataFrame with 'top' and 'bottom' columns.
        """
        buffer = zone_upper * buffer_pct
        
        # In IHQE FVG data structures: top is gap_top, bottom is gap_bottom
        if direction in ["bullish", "bearish"]:
            return df[
                (df["bottom"] >= (zone_lower - buffer)) & 
                (df["top"] <= (zone_upper + buffer))
            ]
            
        return df.iloc[0:0]  # Empty DataFrame if invalid direction

    def get_fvg_zone_mask(
        self,
        bottom_arr: np.ndarray,
        top_arr: np.ndarray,
        zone_lower: float,
        zone_upper: float,
        direction: str,
        buffer_pct: float = 0.005,
    ) -> np.ndarray:
        """
        Numpy vectorized filter applying the exact same logic as _is_fvg_in_zone.
        Returns a boolean mask.
        """
        buffer = zone_upper * buffer_pct
        
        if direction in ["bullish", "bearish"]:
            return (bottom_arr >= (zone_lower - buffer)) & (top_arr <= (zone_upper + buffer))
            
        return np.zeros_like(bottom_arr, dtype=bool)

    def _detect_raw(
        self,
        candles: pd.DataFrame,
        timeframe: str,
        direction: str,
    ) -> list[dict]:
        """
        Detect all FVGs of the given direction on the candle data.
        This is the raw detection — no zone filtering.
        Called internally by detect_in_zone().

        Args:
            candles: OHLCV DataFrame
            timeframe: Canonical timeframe key
            direction: 'bullish' or 'bearish'

        Returns:
            List of raw FVG event dicts
        """
        if len(candles) < 3:
            return []

        fvgs = []
        ts_index = candles.index.tolist()
        highs = candles["high"].values.astype(float)
        lows = candles["low"].values.astype(float)

        for i in range(len(candles) - 2):
            c0_high = highs[i]
            c0_low = lows[i]
            c1_low = lows[i + 1]
            c1_high = highs[i + 1]
            c2_high = highs[i + 2]
            c2_low = lows[i + 2]

            ts_c0 = ts_index[i]
            ts_c2 = ts_index[i + 2]

            if direction == "bullish":
                # BULLISH FVG: candle[2].low > candle[0].high
                if c2_low > c0_high:
                    # Wick rule: candle[1].low must NOT go below candle[0].low
                    if c1_low >= c0_low:
                        gap_top = c2_low
                        gap_bottom = c0_high
                        gap_size = gap_top - gap_bottom
                        mid_price = (gap_top + gap_bottom) / 2
                        gap_size_pct = (
                            (gap_size / mid_price) * 100 if mid_price > 0 else 0
                        )

                        fvgs.append({
                            "fvg_id": str(uuid.uuid4()),
                            "timeframe": timeframe,
                            "direction": "bullish",
                            "ts_candle1": ts_c0,
                            "ts_candle3": ts_c2,
                            "gap_top": float(gap_top),
                            "gap_bottom": float(gap_bottom),
                            "gap_size": float(gap_size),
                            "gap_size_pct": float(gap_size_pct),
                            "is_extreme": 0,
                            "is_mitigated": 0,
                            "ts_mitigated": None,
                            "parent_fvg_id": None,
                        })

            elif direction == "bearish":
                # BEARISH FVG: candle[2].high < candle[0].low
                if c2_high < c0_low:
                    # Wick rule: candle[1].high must NOT go above candle[0].high
                    if c1_high <= c0_high:
                        gap_top = c0_low
                        gap_bottom = c2_high
                        gap_size = gap_top - gap_bottom
                        mid_price = (gap_top + gap_bottom) / 2
                        gap_size_pct = (
                            (gap_size / mid_price) * 100 if mid_price > 0 else 0
                        )

                        fvgs.append({
                            "fvg_id": str(uuid.uuid4()),
                            "timeframe": timeframe,
                            "direction": "bearish",
                            "ts_candle1": ts_c0,
                            "ts_candle3": ts_c2,
                            "gap_top": float(gap_top),
                            "gap_bottom": float(gap_bottom),
                            "gap_size": float(gap_size),
                            "gap_size_pct": float(gap_size_pct),
                            "is_extreme": 0,
                            "is_mitigated": 0,
                            "ts_mitigated": None,
                            "parent_fvg_id": None,
                        })

        return fvgs

    def check_mitigation(
        self,
        fvgs: list[dict],
        candles: pd.DataFrame,
    ) -> list[dict]:
        """
        Check which FVGs have been mitigated by subsequent price action.

        A bullish FVG is mitigated when any candle close <= gap_bottom.
        A bearish FVG is mitigated when any candle close >= gap_top.

        Optimized: pre-computes running min/max of closes.
        """
        if not fvgs or candles.empty:
            return fvgs

        closes = candles["close"].values.astype(float)
        ts_array = candles.index.values
        n = len(closes)

        # Pre-compute running min and max from each index onward
        running_min = np.empty(n, dtype=float)
        running_max = np.empty(n, dtype=float)
        running_min[-1] = closes[-1]
        running_max[-1] = closes[-1]
        for i in range(n - 2, -1, -1):
            running_min[i] = min(running_min[i + 1], closes[i])
            running_max[i] = max(running_max[i + 1], closes[i])

        for fvg in fvgs:
            if fvg["is_mitigated"]:
                continue

            fvg_ts = fvg["ts_candle3"]
            fvg_ts_val = pd.Timestamp(fvg_ts).asm8
            start_idx = np.searchsorted(ts_array, fvg_ts_val, side="right")
            if start_idx >= n:
                continue

            if fvg["direction"] == "bullish":
                if running_min[start_idx] <= fvg["gap_bottom"]:
                    # Vectorized search for first index where condition is met
                    post_closes = closes[start_idx:]
                    idx_offset = np.argmax(post_closes <= fvg["gap_bottom"])
                    fvg["is_mitigated"] = 1
                    fvg["ts_mitigated"] = candles.index[start_idx + idx_offset]

            elif fvg["direction"] == "bearish":
                if running_max[start_idx] >= fvg["gap_top"]:
                    post_closes = closes[start_idx:]
                    idx_offset = np.argmax(post_closes >= fvg["gap_top"])
                    fvg["is_mitigated"] = 1
                    fvg["ts_mitigated"] = candles.index[start_idx + idx_offset]

        return fvgs


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    from database.clickhouse_client import ClickHouseClient

    db = ClickHouseClient()
    detector = FVGDetector()

    # Example: detect bullish FVGs on 3M inside a 12M discount zone
    candles = db.get_ohlcv("3M")
    if not candles.empty:
        # Hypothetical 12M discount zone: $680 to $1377.50
        fvgs = detector.detect_in_zone(
            candles, "3M",
            zone_upper=1377.50,
            zone_lower=680.0,
            direction="bullish",
        )
        print(f"\n3M Bullish FVGs in 12M discount zone: {len(fvgs)}")
        for f in fvgs:
            extreme = " [EXTREME]" if f["is_extreme"] else ""
            print(f"  {f['ts_candle1']} | "
                  f"${f['gap_bottom']:.2f}-${f['gap_top']:.2f} | "
                  f"Size: ${f['gap_size']:.2f}{extreme}")

        # Check mitigation
        fvgs = detector.check_mitigation(fvgs, candles)
        mitigated = sum(1 for f in fvgs if f["is_mitigated"])
        print(f"  Mitigated: {mitigated}/{len(fvgs)}")

    db.close()
