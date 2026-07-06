"""
IHQE v3 — Fibonacci Calculator Unit Tests
"""

import pandas as pd
import numpy as np
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.fibonacci import FibonacciCalculator


def make_candles(data: list[dict]) -> pd.DataFrame:
    """Create a test OHLCV DataFrame from a list of dicts."""
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.set_index("ts", inplace=True)
    return df


class TestFibonacciCalculator:
    """Tests for the FibonacciCalculator class."""

    def setup_method(self):
        self.calc = FibonacciCalculator()

    # ── Level calculation tests ──────────────────────────────────────────────

    def test_bullish_levels(self):
        """Bullish grid levels should count UP from swing_low."""
        grid = self.calc.calculate(
            swing_low=680.0, swing_high=2075.0,
            direction="bullish", timeframe="12M",
            anchor_event_id="test-001",
        )

        assert grid is not None
        assert grid["level_0_000"] == 680.0
        assert grid["level_1_000"] == 2075.0

        total = 2075.0 - 680.0  # 1395.0
        assert abs(grid["level_0_500"] - (2075.0 - 1395.0 * 0.5)) < 0.01
        assert abs(grid["level_0_618"] - (2075.0 - 1395.0 * 0.618)) < 0.01
        assert abs(grid["level_0_786"] - (2075.0 - 1395.0 * 0.786)) < 0.01
        assert abs(grid["level_0_382"] - (2075.0 - 1395.0 * 0.382)) < 0.01
        assert abs(grid["level_0_236"] - (2075.0 - 1395.0 * 0.236)) < 0.01

    def test_bearish_levels(self):
        """Bearish grid levels should count DOWN from swing_high."""
        grid = self.calc.calculate(
            swing_low=1050.0, swing_high=2075.0,
            direction="bearish", timeframe="12M",
            anchor_event_id="test-002",
        )

        assert grid is not None
        assert grid["level_0_000"] == 2075.0   # starting point (top)
        assert grid["level_1_000"] == 1050.0   # target (bottom)

        total = 2075.0 - 1050.0  # 1025.0
        assert abs(grid["level_0_500"] - (1050.0 + 1025.0 * 0.5)) < 0.01
        assert abs(grid["level_0_618"] - (1050.0 + 1025.0 * 0.618)) < 0.01

    def test_all_seven_levels_present(self):
        """Grid should contain all 7 standard Fibonacci levels."""
        grid = self.calc.calculate(
            swing_low=100.0, swing_high=200.0,
            direction="bullish", timeframe="1M",
            anchor_event_id="test-003",
        )

        required_keys = [
            "level_0_000", "level_0_236", "level_0_382",
            "level_0_500", "level_0_618", "level_0_786", "level_1_000",
        ]
        for key in required_keys:
            assert key in grid, f"Missing key: {key}"

    def test_invalid_range_returns_none(self):
        """Grid with swing_high <= swing_low should return None."""
        assert self.calc.calculate(
            swing_low=100.0, swing_high=100.0,
            direction="bullish", timeframe="1M",
            anchor_event_id="test-004",
        ) is None

        assert self.calc.calculate(
            swing_low=200.0, swing_high=100.0,
            direction="bullish", timeframe="1M",
            anchor_event_id="test-005",
        ) is None

    # ── Zone checking tests ──────────────────────────────────────────────────

    def test_is_in_discount_zone(self):
        """Price below 0.5 level should be in discount zone."""
        grid = self.calc.calculate(
            swing_low=680.0, swing_high=2075.0,
            direction="bullish", timeframe="12M",
            anchor_event_id="test-006",
        )

        level_05 = grid["level_0_500"]  # 1377.5
        assert self.calc.is_in_discount_zone(1200.0, grid) is True
        assert self.calc.is_in_discount_zone(1500.0, grid) is False
        assert self.calc.is_in_discount_zone(level_05 - 0.01, grid) is True
        assert self.calc.is_in_discount_zone(level_05 + 0.01, grid) is False

    def test_is_in_premium_zone(self):
        """Price above 0.5 level should be in premium zone."""
        grid = self.calc.calculate(
            swing_low=680.0, swing_high=2075.0,
            direction="bearish", timeframe="12M",
            anchor_event_id="test-007",
        )

        level_05 = grid["level_0_500"]
        assert self.calc.is_in_premium_zone(level_05 + 100, grid) is True
        assert self.calc.is_in_premium_zone(level_05 - 100, grid) is False

    # ── Grid validity tests ──────────────────────────────────────────────────

    def test_bullish_grid_valid(self):
        """Bullish grid valid when price >= swing_low."""
        grid = self.calc.calculate(
            swing_low=680.0, swing_high=2075.0,
            direction="bullish", timeframe="12M",
            anchor_event_id="test-008",
        )

        assert self.calc.is_grid_valid(700.0, grid) is True
        assert self.calc.is_grid_valid(680.0, grid) is True
        assert self.calc.is_grid_valid(679.0, grid) is False

    def test_bearish_grid_valid(self):
        """Bearish grid valid when price <= swing_high."""
        grid = self.calc.calculate(
            swing_low=1050.0, swing_high=2075.0,
            direction="bearish", timeframe="12M",
            anchor_event_id="test-009",
        )

        assert self.calc.is_grid_valid(2000.0, grid) is True
        assert self.calc.is_grid_valid(2075.0, grid) is True
        assert self.calc.is_grid_valid(2076.0, grid) is False

    # ── Grid invalidation with candle data ──────────────────────────────────

    def test_check_grid_invalidation_bullish(self):
        """Bullish grid invalidated when close < swing_low."""
        grid = self.calc.calculate(
            swing_low=680.0, swing_high=2075.0,
            direction="bullish", timeframe="12M",
            anchor_event_id="test-010",
            swing_low_ts=pd.Timestamp("2009-01-01", tz="UTC"),
            swing_high_ts=pd.Timestamp("2020-01-01", tz="UTC"),
        )

        candles = make_candles([
            {"ts": "2021-01-01", "open": 1800, "high": 1900, "low": 1700, "close": 1800},
            {"ts": "2022-01-01", "open": 1800, "high": 1850, "low": 600, "close": 650},
        ])

        grid = self.calc.check_grid_invalidation(grid, candles)
        assert grid["is_active"] == 0

    def test_check_grid_not_invalidated(self):
        """Grid should remain active if no close breaches swing level."""
        grid = self.calc.calculate(
            swing_low=680.0, swing_high=2075.0,
            direction="bullish", timeframe="12M",
            anchor_event_id="test-011",
            swing_low_ts=pd.Timestamp("2009-01-01", tz="UTC"),
            swing_high_ts=pd.Timestamp("2020-01-01", tz="UTC"),
        )

        candles = make_candles([
            {"ts": "2021-01-01", "open": 1800, "high": 1900, "low": 1700, "close": 1800},
            {"ts": "2022-01-01", "open": 1800, "high": 1900, "low": 1750, "close": 1850},
        ])

        grid = self.calc.check_grid_invalidation(grid, candles)
        assert grid["is_active"] == 1

    # ── BOS-anchored grid building ──────────────────────────────────────────

    def test_build_grid_from_bos(self):
        """build_grid_from_bos should use BOS swing points directly."""
        bos = {
            "bos_id": "bos-001",
            "timeframe": "12M",
            "direction": "bullish",
            "bos_candle_ts": pd.Timestamp("2009-01-01", tz="UTC"),
            "swing_low": 680.0,
            "swing_high": 2075.0,
        }

        grid = self.calc.build_grid_from_bos(bos, "12M")

        assert grid is not None
        assert grid["swing_low"] == 680.0
        assert grid["swing_high"] == 2075.0
        assert grid["anchor_event_id"] == "bos-001"
        assert grid["direction"] == "bullish"

    # ── FVG-anchored grid building ──────────────────────────────────────────

    def test_build_grid_from_fvg(self):
        """build_grid_from_fvg should find swing points around FVG."""
        candles = make_candles([
            {"ts": "2014-01-01", "open": 1200, "high": 1250, "low": 1180, "close": 1220},
            {"ts": "2014-04-01", "open": 1220, "high": 1230, "low": 1100, "close": 1120},
            {"ts": "2014-07-01", "open": 1120, "high": 1150, "low": 1050, "close": 1060},
            # FVG candle 0
            {"ts": "2014-10-01", "open": 1060, "high": 1080, "low": 1040, "close": 1070},
            # FVG candle 1 (displacement)
            {"ts": "2015-01-01", "open": 1070, "high": 1120, "low": 1065, "close": 1100},
            # FVG candle 2 (gap: low > candle[0] high → 1090 > 1080)
            {"ts": "2015-04-01", "open": 1100, "high": 1200, "low": 1090, "close": 1180},
            # Forward candles for Point B
            {"ts": "2015-07-01", "open": 1180, "high": 1300, "low": 1170, "close": 1280},
            {"ts": "2015-10-01", "open": 1280, "high": 1350, "low": 1260, "close": 1320},
        ])

        fvg = {
            "fvg_id": "fvg-001",
            "ts_candle1": pd.Timestamp("2014-10-01", tz="UTC"),
            "ts_candle3": pd.Timestamp("2015-04-01", tz="UTC"),
            "gap_top": 1090.0,
            "gap_bottom": 1080.0,
        }

        grid = self.calc.build_grid_from_fvg(
            candles, fvg, "3M",
            direction="bullish",
            lookback=12, forward=6,
        )

        assert grid is not None
        assert grid["swing_low"] <= 1050  # lowest low in lookback
        assert grid["swing_high"] >= 1300  # highest high in forward
        assert grid["anchor_event_id"] == "fvg-001"

    # ── Zone boundary metadata ──────────────────────────────────────────────

    def test_zone_boundary_keys(self):
        """Grid should include discount/premium zone boundary keys."""
        grid = self.calc.calculate(
            swing_low=100.0, swing_high=200.0,
            direction="bullish", timeframe="1M",
            anchor_event_id="test-012",
        )

        assert "discount_zone_upper" in grid
        assert "sniper_zone_deep" in grid
        assert "premium_zone_lower" in grid
        assert "sniper_zone_short" in grid

        assert grid["discount_zone_upper"] == grid["level_0_500"]
        assert grid["sniper_zone_deep"] == grid["level_0_618"]
