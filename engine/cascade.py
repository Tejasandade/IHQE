"""
IHQE v3 — Cascade State Machine

Two-layer cascade system:

Layer 1 — SwingCascade: 3-tier top-down cascade (12M → 3M → 1M)
    12M gate: 'waiting' → 'bos_confirmed' → 'zone_entered'
    3M gate:  'waiting' → 'fvg_confirmed' → 'zone_entered'  (only after 12M zone_entered)
    1M gate:  'waiting' → 'fvg_confirmed' → 'zone_entered'  (only after 3M zone_entered)

Layer 2 — ScalpLayer: 4H + 1H scalp detection
    Activates when SwingCascade.get_gates_confirmed() >= 2
    Path scalps:        SHORT trades riding price TOWARD the 1M discount zone
    Continuation scalps: LONG trades riding price FROM the 1M zone toward 12M target
"""

import logging
import os
import sys
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import settings
from engine.bos_detector import BOSDetector
from engine.fvg_detector import FVGDetector
from engine.fibonacci import FibonacciCalculator

logger = logging.getLogger(__name__)


class SwingGate:
    """Represents a single timeframe gate in the swing cascade."""

    def __init__(self, timeframe: str, direction: str = "bullish"):
        self.timeframe = timeframe
        self.direction = direction
        self.gate_status = "waiting"
        self.confirmed_at: Optional[datetime] = None
        self.fvg_id: Optional[str] = None
        self.bos_id: Optional[str] = None
        self.grid_id: Optional[str] = None
        self.grid: Optional[dict] = None
        self.bos: Optional[dict] = None
        self.fvg: Optional[dict] = None

    def confirm_bos(self, bos: dict, grid: dict, ts: datetime):
        """12M gate: BOS confirmed, grid drawn."""
        self.gate_status = "bos_confirmed"
        self.confirmed_at = ts
        self.bos_id = bos["bos_id"]
        self.grid_id = grid["grid_id"]
        self.bos = bos
        self.grid = grid

    def confirm_fvg(self, fvg: dict, grid: dict, ts: datetime):
        """3M/1M gate: FVG confirmed in parent zone, grid drawn."""
        self.gate_status = "fvg_confirmed"
        self.confirmed_at = ts
        self.fvg_id = fvg["fvg_id"]
        self.grid_id = grid["grid_id"]
        self.fvg = fvg
        self.grid = grid

    def enter_zone(self):
        """Price has entered this gate's zone (ticks below 0.5 for bullish)."""
        if self.gate_status in ("bos_confirmed", "fvg_confirmed"):
            self.gate_status = "zone_entered"

    def reset(self):
        """Reset gate to waiting state."""
        self.gate_status = "waiting"
        self.confirmed_at = None
        self.fvg_id = None
        self.bos_id = None
        self.grid_id = None
        self.grid = None
        self.bos = None
        self.fvg = None

    @property
    def is_confirmed(self) -> bool:
        return self.gate_status in ("bos_confirmed", "fvg_confirmed", "zone_entered")

    def to_dict(self, ts_updated: datetime) -> dict:
        """Convert to dict for database insertion."""
        return {
            "state_id": str(uuid.uuid4()),
            "cascade_type": "primary",
            "direction": self.direction,
            "timeframe": self.timeframe,
            "gate_status": self.gate_status,
            "confirmed_at": self.confirmed_at,
            "fvg_id": self.fvg_id,
            "grid_id": self.grid_id,
            "layer": "swing",
            "ts_updated": ts_updated,
        }


class SwingCascade:
    """
    Manages the 3-tier swing cascade: 12M → 3M → 1M.
    Each gate is strictly sequential — parent must confirm before child opens.
    """

    SWING_TIMEFRAMES = ["12M", "3M", "1M"]

    def __init__(self, db_client, direction: str = "bullish"):
        self.db = db_client
        self.direction = direction
        self.bos_detector = BOSDetector()
        self.fvg_detector = FVGDetector()
        self.fib_calculator = FibonacciCalculator()
        self.gates: dict[str, SwingGate] = {}

        for tf in self.SWING_TIMEFRAMES:
            self.gates[tf] = SwingGate(tf, direction)

    def get_gates_confirmed(self) -> int:
        """
        Returns count of gates with status in
        ('bos_confirmed', 'fvg_confirmed', 'zone_entered').
        Maximum 3 for swing cascade.
        """
        return sum(1 for g in self.gates.values() if g.is_confirmed)

    def get_current_signal_type(self) -> Optional[str]:
        """Returns signal type based on gates_confirmed count."""
        gc = self.get_gates_confirmed()
        if gc == 0:
            return None
        elif gc == 1:
            return "macro_alert"
        elif gc == 2:
            return "mid_alert"
        elif gc >= 3:
            # Check if 1M zone is entered
            if self.gates["1M"].gate_status == "zone_entered":
                return "execute"
            return "active"
        return None

    def is_entry_valid(self) -> bool:
        """True only when all 3 gates are confirmed AND 1M zone is entered."""
        return (
            self.get_gates_confirmed() == 3
            and self.gates["1M"].gate_status == "zone_entered"
        )

    def get_stop_loss(self) -> Optional[float]:
        """Returns the 1M grid level_0_000 (swing low)."""
        gate_1m = self.gates["1M"]
        if gate_1m.grid:
            return gate_1m.grid["level_0_000"]
        return None

    def get_take_profit(self) -> Optional[float]:
        """Returns the 12M grid level_1_000 (swing high)."""
        gate_12m = self.gates["12M"]
        if gate_12m.grid:
            return gate_12m.grid["level_1_000"]
        return None

    def process_bar(self, timeframe: str, candle: dict, live_price: float):
        """
        Called on every new candle for the given timeframe.
        Updates gate states and emits signals when transitions occur.

        Gate transition rules:
            12M: 'waiting' → 'bos_confirmed' (BOSDetector fires)
                 'bos_confirmed' → 'zone_entered' (price ticks below 0.5)

            3M:  Only begins when 12M is 'zone_entered'
                 'waiting' → 'fvg_confirmed' (FVGDetector fires inside 12M zone)
                 'fvg_confirmed' → 'zone_entered' (price ticks below 3M 0.5)

            1M:  Only begins when 3M is 'zone_entered'
                 'waiting' → 'fvg_confirmed' (FVGDetector fires inside 3M zone)
                 'fvg_confirmed' → 'zone_entered' → emit 'active' signal
        """
        if timeframe not in self.SWING_TIMEFRAMES:
            return

        gate = self.gates[timeframe]

        if timeframe == "12M":
            self._process_12m(gate, live_price)
        elif timeframe == "3M":
            self._process_child(gate, self.gates["12M"], live_price)
        elif timeframe == "1M":
            self._process_child(gate, self.gates["3M"], live_price)

    def _process_12m(self, gate: SwingGate, live_price: float):
        """Process the 12M gate — BOS detection only."""
        if gate.gate_status == "waiting":
            # Check for BOS on 12M candles
            candles = self.db.get_ohlcv("12M")
            if candles.empty:
                return

            bos_events = self.bos_detector.detect(candles, "12M")
            active_bos = self.bos_detector.get_active_bos(
                bos_events, "12M", self.direction
            )

            if active_bos:
                # Build Fibonacci grid from BOS swing points
                grid = self.fib_calculator.build_grid_from_bos(active_bos, "12M")
                if grid:
                    grid = self.fib_calculator.check_grid_invalidation(
                        grid, candles
                    )
                    if grid["is_active"]:
                        gate.confirm_bos(active_bos, grid, active_bos["bos_candle_ts"])
                        logger.info(
                            f"12M BOS confirmed: {active_bos['direction']} | "
                            f"Swing: ${active_bos['swing_low']:.2f}-${active_bos['swing_high']:.2f}"
                        )

        elif gate.gate_status == "bos_confirmed":
            # Check if price has entered the discount/premium zone
            if gate.grid:
                if self.direction == "bullish":
                    if self.fib_calculator.is_in_discount_zone(live_price, gate.grid):
                        gate.enter_zone()
                        logger.info(
                            f"12M zone entered: price ${live_price:.2f} below 0.5 "
                            f"(${gate.grid['level_0_500']:.2f})"
                        )
                elif self.direction == "bearish":
                    if self.fib_calculator.is_in_premium_zone(live_price, gate.grid):
                        gate.enter_zone()
                        logger.info(
                            f"12M zone entered: price ${live_price:.2f} above 0.5 "
                            f"(${gate.grid['level_0_500']:.2f})"
                        )

    def _process_child(
        self, gate: SwingGate, parent_gate: SwingGate, live_price: float
    ):
        """Process a child gate (3M or 1M) — requires parent zone_entered."""
        # Parent must have zone_entered before child begins
        if parent_gate.gate_status != "zone_entered":
            return

        if gate.gate_status == "waiting":
            # Look for FVG inside parent's zone
            parent_grid = parent_gate.grid
            if not parent_grid:
                return

            candles = self.db.get_ohlcv(gate.timeframe)
            if candles.empty:
                return

            # Determine zone boundaries from parent grid
            if self.direction == "bullish":
                zone_upper = parent_grid["level_0_500"]
                zone_lower = parent_grid["level_0_000"]
            else:
                zone_upper = parent_grid["level_0_000"]
                zone_lower = parent_grid["level_0_500"]

            fvgs = self.fvg_detector.detect_in_zone(
                candles, gate.timeframe,
                zone_upper=zone_upper,
                zone_lower=zone_lower,
                direction=self.direction,
            )

            if fvgs:
                extreme_fvg = fvgs[0]  # First (extreme) FVG

                lookback = settings.FIB_GRID_LOOKBACK.get(gate.timeframe, settings.FIB_GRID_LOOKBACK.get("default", 12))
                forward = settings.FIB_GRID_FORWARD.get(gate.timeframe, settings.FIB_GRID_FORWARD.get("default", 6))

                grid = self.fib_calculator.build_grid_from_fvg(
                    candles, extreme_fvg, gate.timeframe,
                    direction=self.direction,
                    lookback=lookback, forward=forward,
                    parent_grid_id=parent_gate.grid_id,
                )

                if grid:
                    grid = self.fib_calculator.check_grid_invalidation(grid, candles)
                    if grid["is_active"]:
                        gate.confirm_fvg(extreme_fvg, grid, extreme_fvg["ts_candle3"])
                        logger.info(
                            f"{gate.timeframe} FVG confirmed: "
                            f"${extreme_fvg['gap_bottom']:.2f}-${extreme_fvg['gap_top']:.2f} | "
                            f"Grid: ${grid['swing_low']:.2f}-${grid['swing_high']:.2f}"
                        )

        elif gate.gate_status == "fvg_confirmed":
            # Check if price has entered the zone
            if gate.grid:
                if self.direction == "bullish":
                    if self.fib_calculator.is_in_discount_zone(live_price, gate.grid):
                        gate.enter_zone()
                        logger.info(
                            f"{gate.timeframe} zone entered: price ${live_price:.2f} "
                            f"below 0.5 (${gate.grid['level_0_500']:.2f})"
                        )
                elif self.direction == "bearish":
                    if self.fib_calculator.is_in_premium_zone(live_price, gate.grid):
                        gate.enter_zone()
                        logger.info(
                            f"{gate.timeframe} zone entered: price ${live_price:.2f} "
                            f"above 0.5 (${gate.grid['level_0_500']:.2f})"
                        )

    def run_historical(self) -> dict:
        """
        Run the entire swing cascade on historical data.
        Processes each timeframe in cascade order.

        Returns dict with:
            gates: dict of gate statuses
            grids: dict of grids per timeframe
            bos_events: list of BOS events (12M only)
            fvgs: dict of FVGs per timeframe
            states: list of gate state dicts
        """
        all_bos = []
        all_fvgs = {}
        all_grids = {}
        all_states = []

        print(f"\n{'='*60}")
        print(f"  IHQE v3 Swing Cascade ({self.direction.upper()})")
        print(f"  Timeframes: {' -> '.join(self.SWING_TIMEFRAMES)}")
        print(f"{'='*60}\n")

        for tf in self.SWING_TIMEFRAMES:
            label = settings.TIMEFRAMES[tf]["label"]
            gate = self.gates[tf]

            candles = self.db.get_ohlcv(tf)
            if candles.empty:
                print(f"  [{tf:>3s}] {label:>10s}: No data")
                continue

            live_price = float(candles.iloc[-1]["close"])

            if tf == "12M":
                # 12M: BOS detection + zone entry check
                bos_events = self.bos_detector.detect(candles, tf)
                active_bos = self.bos_detector.get_active_bos(
                    bos_events, tf, self.direction
                )
                all_bos = bos_events

                if active_bos:
                    grid = self.fib_calculator.build_grid_from_bos(active_bos, tf)
                    if grid:
                        grid = self.fib_calculator.check_grid_invalidation(grid, candles)
                        if grid["is_active"]:
                            gate.confirm_bos(active_bos, grid, active_bos["bos_candle_ts"])
                            all_grids[tf] = [grid]

                            # Check zone entry
                            if self.direction == "bullish":
                                if self.fib_calculator.is_in_discount_zone(live_price, grid):
                                    gate.enter_zone()
                            elif self.direction == "bearish":
                                if self.fib_calculator.is_in_premium_zone(live_price, grid):
                                    gate.enter_zone()

                            print(f"  [{tf:>3s}] {label:>10s}: [OK] {gate.gate_status.upper()} — "
                                  f"BOS at {active_bos['bos_candle_ts']} | "
                                  f"Grid ${grid['swing_low']:.2f}-${grid['swing_high']:.2f}")
                        else:
                            all_grids[tf] = []
                            print(f"  [{tf:>3s}] {label:>10s}: [..] BOS found but grid invalidated")
                    else:
                        all_grids[tf] = []
                        print(f"  [{tf:>3s}] {label:>10s}: [..] BOS found but no valid grid")
                else:
                    all_grids[tf] = []
                    print(f"  [{tf:>3s}] {label:>10s}: [..] WAITING — no {self.direction} BOS")

            else:
                # 3M / 1M: FVG detection in parent zone
                parent_tf = self.SWING_TIMEFRAMES[self.SWING_TIMEFRAMES.index(tf) - 1]
                parent_gate = self.gates[parent_tf]

                if parent_gate.gate_status != "zone_entered":
                    all_fvgs[tf] = []
                    all_grids[tf] = []
                    print(f"  [{tf:>3s}] {label:>10s}: [..] WAITING — parent not zone_entered")
                    all_states.append(gate.to_dict(datetime.utcnow()))
                    continue

                parent_grid = parent_gate.grid
                if not parent_grid:
                    all_fvgs[tf] = []
                    all_grids[tf] = []
                    all_states.append(gate.to_dict(datetime.utcnow()))
                    continue

                # Zone boundaries
                if self.direction == "bullish":
                    zone_upper = parent_grid["level_0_500"]
                    zone_lower = parent_grid["level_0_000"]
                else:
                    zone_upper = parent_grid["level_0_000"]
                    zone_lower = parent_grid["level_0_500"]

                fvgs = self.fvg_detector.detect_in_zone(
                    candles, tf,
                    zone_upper=zone_upper, zone_lower=zone_lower,
                    direction=self.direction,
                )
                fvgs = self.fvg_detector.check_mitigation(fvgs, candles)
                all_fvgs[tf] = fvgs

                if fvgs:
                    extreme_fvg = fvgs[0]

                    lookback = settings.FIB_GRID_LOOKBACK.get(tf, settings.FIB_GRID_LOOKBACK.get("default", 12))
                    forward = settings.FIB_GRID_FORWARD.get(tf, settings.FIB_GRID_FORWARD.get("default", 6))

                    grid = self.fib_calculator.build_grid_from_fvg(
                        candles, extreme_fvg, tf,
                        direction=self.direction,
                        lookback=lookback, forward=forward,
                        parent_grid_id=parent_gate.grid_id,
                    )

                    if grid:
                        grid = self.fib_calculator.check_grid_invalidation(grid, candles)
                        if grid["is_active"]:
                            gate.confirm_fvg(extreme_fvg, grid, extreme_fvg["ts_candle3"])
                            all_grids[tf] = [grid]

                            # Check zone entry
                            if self.direction == "bullish":
                                if self.fib_calculator.is_in_discount_zone(live_price, grid):
                                    gate.enter_zone()
                            elif self.direction == "bearish":
                                if self.fib_calculator.is_in_premium_zone(live_price, grid):
                                    gate.enter_zone()

                            print(f"  [{tf:>3s}] {label:>10s}: [OK] {gate.gate_status.upper()} — "
                                  f"FVG ${extreme_fvg['gap_bottom']:.2f}-${extreme_fvg['gap_top']:.2f} | "
                                  f"Grid ${grid['swing_low']:.2f}-${grid['swing_high']:.2f}")
                        else:
                            all_grids[tf] = []
                            print(f"  [{tf:>3s}] {label:>10s}: [..] FVG found but grid invalidated")
                    else:
                        all_grids[tf] = []
                        print(f"  [{tf:>3s}] {label:>10s}: [..] FVG in zone but no valid grid")
                else:
                    all_grids[tf] = []
                    print(f"  [{tf:>3s}] {label:>10s}: [..] WAITING — no {self.direction} FVG in parent zone")

            all_states.append(gate.to_dict(datetime.utcnow()))

        # Store results
        self._store_results(all_bos, all_fvgs, all_grids, all_states)

        print(f"\n  Gates Confirmed: {self.get_gates_confirmed()}/3")
        signal = self.get_current_signal_type()
        if signal:
            print(f"  Signal: {signal.upper()}")
        if self.is_entry_valid():
            print(f"  ENTRY VALID — SL: ${self.get_stop_loss():.2f} | TP: ${self.get_take_profit():.2f}")
        print(f"{'='*60}")

        return {
            "gates": {tf: g.gate_status for tf, g in self.gates.items()},
            "gates_confirmed": self.get_gates_confirmed(),
            "bos_events": all_bos,
            "fvgs": all_fvgs,
            "grids": all_grids,
            "states": all_states,
            "signal_type": self.get_current_signal_type(),
        }

    def _store_results(
        self, bos_events, fvgs, grids, states
    ) -> None:
        """Store all cascade results in the database."""
        # BOS events
        if bos_events:
            self.db.clear_bos_events("12M")
            self.db.insert_bos_events(bos_events)

        # FVGs
        for tf, tf_fvgs in fvgs.items():
            if tf_fvgs:
                self.db.clear_fvg_events(tf)
                self.db.insert_fvg_events(tf_fvgs)

        # Grids
        for tf, tf_grids in grids.items():
            if tf_grids:
                self.db.clear_fib_grids(tf)
                self.db.insert_fib_grids(tf_grids)

        # States
        if states:
            self.db.insert_cascade_states(states)


class ScalpLayer:
    """
    Manages 4H and 1H scalp detection inside confirmed swing structure.
    Only activates when SwingCascade.get_gates_confirmed() >= 2.
    """

    SCALP_TIMEFRAMES = ["4H", "1H"]

    def __init__(self, db_client):
        self.db = db_client
        self.bos_detector = BOSDetector()
        self.fvg_detector = FVGDetector()
        self.fib_calculator = FibonacciCalculator()
        self.scalp_setups: list[dict] = []

    def process_bar(
        self,
        timeframe: str,
        candle: dict,
        swing_cascade: SwingCascade,
    ):
        """
        Detects scalp setups on 4H and 1H.
        Uses the same BOS → FVG → Fibonacci logic as swing cascade
        but on lower timeframes.

        Determines scalp type based on swing context:
            - If swing 1M entry not yet taken: scalp_path (short)
            - If swing 1M entry taken: scalp_cont (long)
        """
        if timeframe not in self.SCALP_TIMEFRAMES:
            return

        # Scalp layer only activates with >= 2 swing gates confirmed
        if swing_cascade.get_gates_confirmed() < 2:
            return

        candles = self.db.get_ohlcv(timeframe)
        if candles.empty:
            return

        live_price = float(candles.iloc[-1]["close"])

        # Determine scalp type
        swing_1m_entered = swing_cascade.gates["1M"].gate_status == "zone_entered"
        if swing_1m_entered:
            scalp_type = "scalp_cont"
            scalp_direction = swing_cascade.direction  # same as swing (long)
        else:
            scalp_type = "scalp_path"
            # Counter-direction for path scalps
            scalp_direction = "bearish" if swing_cascade.direction == "bullish" else "bullish"

        # Detect BOS on this timeframe
        bos_events = self.bos_detector.detect(candles, timeframe)
        active_bos = self.bos_detector.get_active_bos(
            bos_events, timeframe, scalp_direction
        )

        if not active_bos:
            return

        # Build grid from BOS
        grid = self.fib_calculator.build_grid_from_bos(active_bos, timeframe)
        if not grid or not grid["is_active"]:
            return

        grid = self.fib_calculator.check_grid_invalidation(grid, candles)
        if not grid["is_active"]:
            return

        # Detect FVG in the appropriate zone
        if scalp_type == "scalp_path":
            # Path scalp (short): look for bearish FVG in premium zone
            zone_upper = grid["level_0_000"]  # swing_high for bearish
            zone_lower = grid["level_0_500"]
        else:
            # Continuation (long): look for bullish FVG in discount zone
            zone_upper = grid["level_0_500"]
            zone_lower = grid["level_0_000"]

        fvgs = self.fvg_detector.detect_in_zone(
            candles, timeframe,
            zone_upper=zone_upper,
            zone_lower=zone_lower,
            direction=scalp_direction,
        )

        if fvgs:
            extreme_fvg = fvgs[0]
            fvg_grid = self.fvg_detector.check_mitigation([extreme_fvg], candles)

            # Build entry/SL/TP for scalp
            if scalp_type == "scalp_path":
                entry = grid["level_0_500"]  # Enter at premium zone
                stop = grid["level_0_000"]   # Stop above swing high
                # Target: nearest discount zone or 1M 0.5 level
                target_1m_grid = swing_cascade.gates.get("1M", SwingGate("1M"))
                if target_1m_grid.grid:
                    target = target_1m_grid.grid["level_0_500"]
                else:
                    target = grid["level_1_000"]
            else:
                entry = grid["level_0_500"]  # Enter at discount zone
                stop = grid["level_0_000"]   # Stop below swing low
                target = swing_cascade.get_take_profit() or grid["level_1_000"]

            setup = {
                "scalp_type": scalp_type,
                "timeframe": timeframe,
                "direction": "short" if scalp_type == "scalp_path" else "long",
                "entry_price": entry,
                "stop_loss": stop,
                "take_profit": target,
                "bos": active_bos,
                "fvg": extreme_fvg,
                "grid": grid,
            }
            self.scalp_setups.append(setup)

            logger.info(
                f"Scalp setup: {scalp_type} {timeframe} | "
                f"Entry: ${entry:.2f} SL: ${stop:.2f} TP: ${target:.2f}"
            )

    def run_historical(self, swing_cascade: SwingCascade) -> list[dict]:
        """Run scalp detection on historical data for all scalp timeframes."""
        print(f"\n{'='*60}")
        print(f"  IHQE v3 Scalp Layer")
        print(f"  Swing gates confirmed: {swing_cascade.get_gates_confirmed()}/3")
        print(f"{'='*60}\n")

        if swing_cascade.get_gates_confirmed() < 2:
            print(f"  Scalp layer INACTIVE — need >= 2 swing gates confirmed")
            print(f"{'='*60}")
            return []

        for tf in self.SCALP_TIMEFRAMES:
            candles = self.db.get_ohlcv(tf)
            if candles.empty:
                print(f"  [{tf:>3s}] No data")
                continue

            dummy_candle = candles.iloc[-1].to_dict()
            self.process_bar(tf, dummy_candle, swing_cascade)

            label = settings.TIMEFRAMES[tf]["label"]
            tf_setups = [s for s in self.scalp_setups if s["timeframe"] == tf]
            if tf_setups:
                for s in tf_setups:
                    print(f"  [{tf:>3s}] {label:>10s}: {s['scalp_type'].upper()} {s['direction'].upper()} | "
                          f"Entry: ${s['entry_price']:.2f} SL: ${s['stop_loss']:.2f} TP: ${s['take_profit']:.2f}")
            else:
                print(f"  [{tf:>3s}] {label:>10s}: No scalp setups")

        print(f"\n  Total scalp setups: {len(self.scalp_setups)}")
        print(f"{'='*60}")

        return self.scalp_setups


def run_full_cascade(db_client) -> dict:
    """Run the complete cascade analysis — swing + scalp.

    Returns dict with swing and scalp results.
    """
    results = {}

    for direction in ["bullish", "bearish"]:
        swing = SwingCascade(db_client, direction)
        swing_results = swing.run_historical()

        scalp = ScalpLayer(db_client)
        scalp_results = scalp.run_historical(swing)

        results[direction] = {
            "swing": swing_results,
            "scalp": scalp_results,
            "gates_confirmed": swing.get_gates_confirmed(),
            "signal_type": swing.get_current_signal_type(),
            "entry_valid": swing.is_entry_valid(),
        }

    # Determine macro trend
    bull_gates = results["bullish"]["gates_confirmed"]
    bear_gates = results["bearish"]["gates_confirmed"]
    results["macro_trend"] = "bullish" if bull_gates >= bear_gates else "bearish"

    print(f"\n  Macro Trend: {results['macro_trend'].upper()}")
    print(f"  Bullish swing gates: {bull_gates}/3")
    print(f"  Bearish swing gates: {bear_gates}/3")

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    from database.clickhouse_client import ClickHouseClient
    db = ClickHouseClient()
    run_full_cascade(db)
    db.close()
