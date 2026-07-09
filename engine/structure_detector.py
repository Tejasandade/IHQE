"""
IHQE v3 — Independent Structure Detector

Runs BOS, Fibonacci, and FVG detection independently on ANY timeframe.
This populates chart overlays without requiring cascade gate progression.

The cascade gates (12M→3M→1M) remain for signal generation only.
This module ensures every chart has rich structure markings.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.bos_detector import BOSDetector
from engine.fvg_detector import FVGDetector
from engine.fibonacci import FibonacciCalculator

logger = logging.getLogger(__name__)

# All timeframes that should have independent structure detection
ALL_TIMEFRAMES = ["12M", "3M", "1M", "W", "4H", "1H"]


class StructureDetector:
    """
    Detects BOS, Fibonacci grids, and FVG zones on any timeframe
    independently — no cascade gating required.

    This is the "video replay" mode: walk through all historical data
    and mark every structural event.
    """

    def __init__(self, db_client):
        self.db = db_client
        self.bos_detector = BOSDetector()
        self.fvg_detector = FVGDetector()
        self.fib_calculator = FibonacciCalculator()

    def detect_all_structure(self, timeframe: str) -> dict:
        """
        Run full independent structure detection on a single timeframe.

        Steps:
            1. Load OHLCV candles
            2. Detect ALL BOS events (bullish + bearish)
            3. For each active BOS → build Fibonacci grid
            4. For each active grid → detect FVGs in discount/premium zone
            5. Store everything in ClickHouse

        Returns:
            dict with counts of detected structure
        """
        candles = self.db.get_ohlcv(timeframe)
        if candles.empty:
            print(f"  [{timeframe:>3s}] No data available")
            return {"bos": 0, "grids": 0, "fvgs": 0}

        # ── Step 1: Detect ALL BOS events ─────────────────────────────
        bos_events = self.bos_detector.detect(candles, timeframe)

        bullish_bos = [b for b in bos_events if b["direction"] == "bullish"]
        bearish_bos = [b for b in bos_events if b["direction"] == "bearish"]
        active_bos = [b for b in bos_events if b["is_active"] == 1]

        # ── Step 2: Build Fibonacci grids for active BOS events ────────
        all_grids = []

        # Get the most recent active bullish BOS
        bullish_active = self.bos_detector.get_active_bos(
            bos_events, timeframe, "bullish"
        )
        if bullish_active:
            grid = self.fib_calculator.build_grid_from_bos(bullish_active, timeframe)
            if grid:
                grid = self.fib_calculator.check_grid_invalidation(grid, candles)
                if grid["is_active"]:
                    all_grids.append(grid)

        # Get the most recent active bearish BOS
        bearish_active = self.bos_detector.get_active_bos(
            bos_events, timeframe, "bearish"
        )
        if bearish_active:
            grid = self.fib_calculator.build_grid_from_bos(bearish_active, timeframe)
            if grid:
                grid = self.fib_calculator.check_grid_invalidation(grid, candles)
                if grid["is_active"]:
                    all_grids.append(grid)

        # ── Step 3: Detect FVGs inside each active grid's zone ─────────
        all_fvgs = []

        for grid in all_grids:
            direction = grid.get("direction", "bullish")

            # Define zone boundaries based on direction
            if direction == "bullish":
                zone_upper = grid["level_0_500"]
                zone_lower = grid["level_0_000"]
            else:
                zone_upper = grid["level_0_000"]  # swing_high for bearish
                zone_lower = grid["level_0_500"]

            fvgs = self.fvg_detector.detect_in_zone(
                candles, timeframe,
                zone_upper=zone_upper,
                zone_lower=zone_lower,
                direction=direction,
            )
            fvgs = self.fvg_detector.check_mitigation(fvgs, candles)
            all_fvgs.extend(fvgs)

        # ── Step 4: Store in ClickHouse ────────────────────────────────
        # Clear old data for this timeframe and insert fresh
        if bos_events:
            self.db.clear_bos_events(timeframe)
            self.db.insert_bos_events(bos_events)

        if all_grids:
            self.db.clear_fib_grids(timeframe)
            self.db.insert_fib_grids(all_grids)

        if all_fvgs:
            self.db.clear_fvg_events(timeframe)
            self.db.insert_fvg_events(all_fvgs)

        # ── Print summary ─────────────────────────────────────────────
        print(
            f"  [{timeframe:>3s}] "
            f"BOS: {len(bullish_bos)} bull {len(bearish_bos)} bear "
            f"(active: {len(active_bos)}) | "
            f"Grids: {len(all_grids)} | "
            f"FVGs: {len(all_fvgs)}"
        )

        return {
            "bos": len(bos_events),
            "grids": len(all_grids),
            "fvgs": len(all_fvgs),
        }

    def detect_incremental(self, timeframe: str) -> dict:
        """
        Run incremental structure detection.
        Only processes candles since the oldest ACTIVE BOS to correctly 
        detect new events and invalidate old active ones without a full 22-year scan.
        """
        import time
        start_time = time.time()
        
        last_ts = self.db.get_latest_structure_ts(timeframe)
        if not last_ts:
            return self.detect_all_structure(timeframe)

        active_bos_df = self.db.get_bos_events(timeframe, active_only=True)
        if not active_bos_df.empty:
            # We only need to go back as far as the most recent active bullish/bearish BOS
            # to ensure they are properly invalidated if price moves against them.
            latest_bull = active_bos_df[active_bos_df["direction"] == "bullish"]
            latest_bear = active_bos_df[active_bos_df["direction"] == "bearish"]
            
            ts_to_check = []
            if not latest_bull.empty:
                ts_to_check.append(latest_bull["bos_candle_ts"].max())
            if not latest_bear.empty:
                ts_to_check.append(latest_bear["bos_candle_ts"].max())
                
            if ts_to_check:
                start_search_ts = str(min(ts_to_check))
            else:
                start_search_ts = last_ts
        else:
            start_search_ts = last_ts

        candles = self.db.get_ohlcv(timeframe)
        if candles.empty:
            return {"bos": 0, "grids": 0, "fvgs": 0}

        try:
            start_idx = candles.index.get_loc(start_search_ts)
            if isinstance(start_idx, slice):
                start_idx = start_idx.start
            slice_start = max(0, start_idx - 100)
        except (KeyError, TypeError):
            slice_start = max(0, len(candles) - 1000)

        incremental_candles = candles.iloc[slice_start:]
        
        if timeframe in ["1H", "4H"] and len(incremental_candles) > 500:
            logger.warning(
                f"[{timeframe}] Incremental scan capped at 500 bars (was {len(incremental_candles)}). "
                f"Some older active BOS events may not be invalidated."
            )
            incremental_candles = incremental_candles.iloc[-500:]

        if len(incremental_candles) < 7:
            return {"bos": 0, "grids": 0, "fvgs": 0}

        bos_events = self.bos_detector.detect(incremental_candles, timeframe)
        bullish_bos = [b for b in bos_events if b["direction"] == "bullish"]
        bearish_bos = [b for b in bos_events if b["direction"] == "bearish"]
        active_bos = [b for b in bos_events if b.get("is_active", 1) == 1]

        all_grids = []
        bullish_active = self.bos_detector.get_active_bos(bos_events, timeframe, "bullish")
        if bullish_active:
            grid = self.fib_calculator.build_grid_from_bos(bullish_active, timeframe)
            if grid:
                grid = self.fib_calculator.check_grid_invalidation(grid, incremental_candles)
                if grid["is_active"]:
                    all_grids.append(grid)

        bearish_active = self.bos_detector.get_active_bos(bos_events, timeframe, "bearish")
        if bearish_active:
            grid = self.fib_calculator.build_grid_from_bos(bearish_active, timeframe)
            if grid:
                grid = self.fib_calculator.check_grid_invalidation(grid, incremental_candles)
                if grid["is_active"]:
                    all_grids.append(grid)

        all_fvgs = []
        for grid in all_grids:
            direction = grid.get("direction", "bullish")
            if direction == "bullish":
                zone_upper = grid["level_0_500"]
                zone_lower = grid["level_0_000"]
            else:
                zone_upper = grid["level_0_000"]
                zone_lower = grid["level_0_500"]

            fvgs = self.fvg_detector.detect_in_zone(
                incremental_candles, timeframe,
                zone_upper=zone_upper,
                zone_lower=zone_lower,
                direction=direction,
            )
            fvgs = self.fvg_detector.check_mitigation(fvgs, incremental_candles)
            all_fvgs.extend(fvgs)

        # Insert to ClickHouse - ReplacingMergeTree will automatically overwrite
        # records with the same primary keys
        if bos_events:
            self.db.insert_bos_events(bos_events)
        if all_grids:
            self.db.insert_fib_grids(all_grids)
        if all_fvgs:
            self.db.insert_fvg_events(all_fvgs)

        elapsed = time.time() - start_time
        print(
            f"  [{timeframe:>3s}] INC ({len(incremental_candles)} bars) "
            f"BOS: {len(bullish_bos)} bull {len(bearish_bos)} bear "
            f"(active: {len(active_bos)}) | "
            f"Grids: {len(all_grids)} | "
            f"FVGs: {len(all_fvgs)} | "
            f"{elapsed:.3f}s"
        )
        return {
            "bos": len(bos_events),
            "grids": len(all_grids),
            "fvgs": len(all_fvgs),
        }

    def detect_all_timeframes(self, incremental: bool = True) -> dict:
        """
        Run structure detection on ALL timeframes.
        This is the main entry point for the historical replay.
        """
        print(f"\n{'='*60}")
        print(f"  IHQE v3 — Independent Structure Detection")
        print(f"  Timeframes: {', '.join(ALL_TIMEFRAMES)}")
        print(f"  Mode: {'Incremental' if incremental else 'Full'}")
        print(f"{'='*60}\n")

        results = {}
        for tf in ALL_TIMEFRAMES:
            if incremental:
                results[tf] = self.detect_incremental(tf)
            else:
                results[tf] = self.detect_all_structure(tf)

        total_bos = sum(r["bos"] for r in results.values())
        total_grids = sum(r["grids"] for r in results.values())
        total_fvgs = sum(r["fvgs"] for r in results.values())

        print(f"\n  Total: {total_bos} BOS | {total_grids} grids | {total_fvgs} FVGs")
        print(f"{'='*60}\n")

        return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    from database.clickhouse_client import ClickHouseClient

    db = ClickHouseClient()
    detector = StructureDetector(db)
    
    # Startup validation check
    try:
        bos_df = db.query_df("SELECT count() as c FROM ihqe.bos_events")
        bos_count = bos_df.iloc[0, 0] if not bos_df.empty else 0
        
        candle_df = db.query_df("SELECT count() as c FROM ihqe.xauusd_ohlcv WHERE timeframe = '12M'")
        candle_count = candle_df.iloc[0, 0] if not candle_df.empty else 0
        
        if candle_count > 0 and (bos_count / candle_count) < 0.5:
            logging.warning(f"WARNING: BOS event count too low for dataset size ({bos_count} BOS / {candle_count} 12M candles). Running full structure scan.")
            detector.detect_all_timeframes(incremental=False)
        else:
            detector.detect_all_timeframes(incremental=True)
    except Exception as e:
        logging.error(f"Failed startup validation check: {e}")
        detector.detect_all_timeframes(incremental=True)
        
    db.close()
