"""
IHQE v3 — Fibonacci Grid Calculator

Calculates Fibonacci retracement grids anchored to BOS-defined swing points.

For BULLISH grids:
    Levels count UP from swing_low to swing_high.
    level_0_000 = swing_low (bottom)
    level_1_000 = swing_high (top)
    Retracement levels measure pullback from high toward low.
    Discount zone = everything below 0.5 level.

For BEARISH grids:
    Levels count DOWN from swing_high to swing_low.
    level_0_000 = swing_high (top, starting point)
    level_1_000 = swing_low (bottom, target)
    Retracement levels measure rally from low toward high.
    Premium zone = everything above 0.5 level.

Grid invalidation:
    Bullish grid: invalidated if price closes below swing_low (level_0_000)
    Bearish grid: invalidated if price closes above swing_high (level_0_000)
"""

import logging
import os
import sys
import uuid
from typing import Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import settings

logger = logging.getLogger(__name__)

# Standard Fibonacci retracement levels
FIB_RATIOS = {
    "level_1_000": 1.000,
    "level_0_786": 0.786,
    "level_0_618": 0.618,
    "level_0_500": 0.500,
    "level_0_382": 0.382,
    "level_0_236": 0.236,
    "level_0_000": 0.000,
}


class FibonacciCalculator:
    """
    Calculates Fibonacci grids anchored to BOS-defined swing points.
    """

    def calculate(
        self,
        swing_low: float,
        swing_high: float,
        direction: str,
        timeframe: str,
        anchor_event_id: str,
        swing_low_ts=None,
        swing_high_ts=None,
        parent_grid_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Calculate a complete Fibonacci grid from swing points.

        Args:
            swing_low: The low point of the swing
            swing_high: The high point of the swing
            direction: 'bullish' or 'bearish'
            timeframe: Canonical timeframe key
            anchor_event_id: bos_id or fvg_id that triggered this grid
            swing_low_ts: Timestamp of the swing low candle
            swing_high_ts: Timestamp of the swing high candle
            parent_grid_id: Optional parent grid for cascade linking

        Returns:
            Dict with all 7 levels plus zone boundaries and metadata,
            or None if inputs are invalid.
        """
        if swing_high <= swing_low:
            logger.debug(
                f"Invalid swing range: high={swing_high}, low={swing_low}"
            )
            return None

        total_range = swing_high - swing_low

        if direction == "bullish":
            # Bullish: levels are measured as retracements from swing_high
            # level_1_000 = swing_high (top)
            # level_0_000 = swing_low (bottom)
            levels = {
                "level_1_000": swing_high,
                "level_0_786": swing_high - (total_range * 0.786),
                "level_0_618": swing_high - (total_range * 0.618),
                "level_0_500": swing_high - (total_range * 0.500),
                "level_0_382": swing_high - (total_range * 0.382),
                "level_0_236": swing_high - (total_range * 0.236),
                "level_0_000": swing_low,
            }
        elif direction == "bearish":
            # Bearish: levels are measured as retracements from swing_low
            # level_1_000 = swing_low (bottom, target)
            # level_0_000 = swing_high (top, starting point)
            levels = {
                "level_1_000": swing_low,
                "level_0_786": swing_low + (total_range * 0.786),
                "level_0_618": swing_low + (total_range * 0.618),
                "level_0_500": swing_low + (total_range * 0.500),
                "level_0_382": swing_low + (total_range * 0.382),
                "level_0_236": swing_low + (total_range * 0.236),
                "level_0_000": swing_high,
            }
        else:
            logger.error(f"Invalid direction: {direction}")
            return None

        grid = {
            "grid_id": str(uuid.uuid4()),
            "timeframe": timeframe,
            "direction": direction,
            "anchor_event_id": anchor_event_id,
            "swing_low_ts": swing_low_ts,
            "swing_high_ts": swing_high_ts,
            "swing_low": swing_low,
            "swing_high": swing_high,
            "total_range": total_range,
            "is_active": 1,
            "parent_grid_id": parent_grid_id,
            # Zone boundaries for quick access
            "discount_zone_upper": levels["level_0_500"],
            "sniper_zone_deep": levels["level_0_618"],
            "premium_zone_lower": levels["level_0_500"],
            "sniper_zone_short": levels["level_0_382"],
        }
        grid.update(levels)

        return grid

    def is_in_discount_zone(self, price: float, grid: dict) -> bool:
        """
        Returns True if price is below the grid's 0.5 level.
        Used for bullish setups — price is in the "discount" area.
        """
        return price < grid["level_0_500"]

    def is_in_premium_zone(self, price: float, grid: dict) -> bool:
        """
        Returns True if price is above the grid's 0.5 level.
        Used for bearish setups — price is in the "premium" area.
        """
        return price > grid["level_0_500"]

    def is_grid_valid(self, price: float, grid: dict) -> bool:
        """
        Check if a grid is still structurally valid.

        Bullish grid: invalid if price closes below level_0_000 (swing_low).
        Bearish grid: invalid if price closes above level_0_000 (swing_high).
        """
        if grid["direction"] == "bullish":
            return price >= grid["level_0_000"]
        elif grid["direction"] == "bearish":
            return price <= grid["level_0_000"]
        return False

    def check_grid_invalidation(
        self, grid: dict, candles: pd.DataFrame
    ) -> dict:
        """
        Check if a Fibonacci grid has been invalidated by price action
        after the grid was established.

        Returns the grid dict with is_active updated.
        """
        if not grid.get("is_active", 1):
            return grid

        # Only check candles after the grid was established
        grid_end_ts = max(
            grid.get("swing_low_ts") or pd.Timestamp.min,
            grid.get("swing_high_ts") or pd.Timestamp.min,
        )
        if grid_end_ts == pd.Timestamp.min:
            return grid

        post_candles = candles[candles.index > grid_end_ts]
        if post_candles.empty:
            return grid

        closes = post_candles["close"].values.astype(float)

        if grid["direction"] == "bullish":
            # Invalidated if any close below swing_low
            if np.any(closes < grid["swing_low"]):
                grid["is_active"] = 0
        elif grid["direction"] == "bearish":
            # Invalidated if any close above swing_high
            if np.any(closes > grid["swing_high"]):
                grid["is_active"] = 0

        return grid

    def build_grid_from_bos(
        self,
        bos_event: dict,
        timeframe: str,
        parent_grid_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Convenience method: build a Fibonacci grid directly from a BOS event.
        The BOS event already contains swing_low and swing_high.
        """
        return self.calculate(
            swing_low=bos_event["swing_low"],
            swing_high=bos_event["swing_high"],
            direction=bos_event["direction"],
            timeframe=timeframe,
            anchor_event_id=bos_event["bos_id"],
            swing_low_ts=bos_event.get("swing_low_ts", bos_event.get("bos_candle_ts")),
            swing_high_ts=bos_event.get("swing_high_ts", bos_event.get("bos_candle_ts")),
            parent_grid_id=parent_grid_id,
        )

    def build_grid_from_fvg(
        self,
        candles: pd.DataFrame,
        fvg: dict,
        timeframe: str,
        direction: str,
        lookback: int = 12,
        forward: int = 6,
        parent_grid_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Build a Fibonacci grid from an FVG event on 3M or 1M timeframes.

        Point A = lowest low of the structural leg that created the FVG
                  (scan back up to `lookback` candles before the FVG candle[0])
        Point B = highest high after the FVG formation
                  (scan forward up to `forward` candles after candle[2])

        Args:
            candles: OHLCV DataFrame
            fvg: FVG event dict
            timeframe: Canonical timeframe key
            direction: 'bullish' or 'bearish'
            lookback: Number of candles to scan back for Point A
            forward: Number of candles to scan forward for Point B
            parent_grid_id: Optional parent grid

        Returns:
            Fibonacci grid dict or None
        """
        fvg_ts = fvg["ts_candle1"]

        # Find the position of the FVG in the candle data
        if fvg_ts in candles.index:
            fvg_pos = candles.index.get_loc(fvg_ts)
        else:
            fvg_pos = candles.index.searchsorted(fvg_ts)
            if fvg_pos >= len(candles):
                return None

        highs = candles["high"].values.astype(float)
        lows = candles["low"].values.astype(float)

        if direction == "bullish":
            # Point A = lowest low scanning back from FVG
            scan_start = max(0, fvg_pos - lookback)
            point_a = float(np.min(lows[scan_start:fvg_pos + 1]))
            point_a_idx = scan_start + int(np.argmin(lows[scan_start:fvg_pos + 1]))

            # Point B = highest high scanning forward from FVG end (candle[2])
            fvg_end = min(len(candles), fvg_pos + 3)  # FVG is 3 candles
            scan_end = min(len(candles), fvg_end + forward)
            point_b = float(np.max(highs[fvg_end:scan_end])) if fvg_end < scan_end else float(highs[fvg_pos])
            point_b_idx = fvg_end + int(np.argmax(highs[fvg_end:scan_end])) if fvg_end < scan_end else fvg_pos

            swing_low = point_a
            swing_high = point_b
            swing_low_ts = candles.index[point_a_idx]
            swing_high_ts = candles.index[min(point_b_idx, len(candles) - 1)]

        elif direction == "bearish":
            # Point A = highest high scanning back from FVG
            scan_start = max(0, fvg_pos - lookback)
            point_a = float(np.max(highs[scan_start:fvg_pos + 1]))
            point_a_idx = scan_start + int(np.argmax(highs[scan_start:fvg_pos + 1]))

            # Point B = lowest low scanning forward from FVG end
            fvg_end = min(len(candles), fvg_pos + 3)
            scan_end = min(len(candles), fvg_end + forward)
            point_b = float(np.min(lows[fvg_end:scan_end])) if fvg_end < scan_end else float(lows[fvg_pos])
            point_b_idx = fvg_end + int(np.argmin(lows[fvg_end:scan_end])) if fvg_end < scan_end else fvg_pos

            swing_high = point_a
            swing_low = point_b
            swing_high_ts = candles.index[point_a_idx]
            swing_low_ts = candles.index[min(point_b_idx, len(candles) - 1)]
        else:
            return None

        return self.calculate(
            swing_low=swing_low,
            swing_high=swing_high,
            direction=direction,
            timeframe=timeframe,
            anchor_event_id=fvg["fvg_id"],
            swing_low_ts=swing_low_ts,
            swing_high_ts=swing_high_ts,
            parent_grid_id=parent_grid_id,
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    calc = FibonacciCalculator()

    # Example: XAU/USD 12M bullish grid (2008 low to 2020 high)
    grid = calc.calculate(
        swing_low=680.0,
        swing_high=2075.0,
        direction="bullish",
        timeframe="12M",
        anchor_event_id="test-bos-001",
    )

    if grid:
        print(f"\nExample 12M Bullish Grid: ${grid['swing_low']:.2f} - ${grid['swing_high']:.2f}")
        print(f"  1.000 (swing high): ${grid['level_1_000']:.2f}")
        print(f"  0.786:             ${grid['level_0_786']:.2f}")
        print(f"  0.618 (sniper):    ${grid['level_0_618']:.2f}")
        print(f"  0.500 (zone bnd):  ${grid['level_0_500']:.2f}")
        print(f"  0.382:             ${grid['level_0_382']:.2f}")
        print(f"  0.236:             ${grid['level_0_236']:.2f}")
        print(f"  0.000 (swing low): ${grid['level_0_000']:.2f}")
        print(f"\n  In discount at $1200? {calc.is_in_discount_zone(1200.0, grid)}")
        print(f"  In premium at $1500?  {calc.is_in_premium_zone(1500.0, grid)}")
        print(f"  Grid valid at $700?   {calc.is_grid_valid(700.0, grid)}")
        print(f"  Grid valid at $600?   {calc.is_grid_valid(600.0, grid)}")
