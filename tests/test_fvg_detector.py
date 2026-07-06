"""
IHQE v3 — FVG Detector Unit Tests
"""

import pandas as pd
import numpy as np
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.fvg_detector import FVGDetector


def make_candles(data: list[dict]) -> pd.DataFrame:
    """Create a test OHLCV DataFrame from a list of dicts."""
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.set_index("ts", inplace=True)
    return df


class TestFVGDetector:
    """Tests for the FVGDetector class."""

    def setup_method(self):
        self.detector = FVGDetector()

    # ── Bullish FVG detection ────────────────────────────────────────────────

    def test_bullish_fvg_detected_in_zone(self):
        """Bullish FVG: candle[2].low > candle[0].high, within zone."""
        candles = make_candles([
            # Candle 0: high = 1080
            {"ts": "2015-01-01", "open": 1050, "high": 1080, "low": 1040, "close": 1060},
            # Candle 1: displacement (low must NOT go below candle[0].low = 1040)
            {"ts": "2015-04-01", "open": 1060, "high": 1120, "low": 1055, "close": 1100},
            # Candle 2: low = 1090 > candle[0].high = 1080 → FVG!
            {"ts": "2015-07-01", "open": 1100, "high": 1150, "low": 1090, "close": 1130},
        ])

        fvgs = self.detector.detect_in_zone(
            candles, "3M",
            zone_upper=1377.5,  # 12M 0.5 level
            zone_lower=680.0,   # 12M swing low
            direction="bullish",
        )

        assert len(fvgs) >= 1
        fvg = fvgs[0]
        assert fvg["direction"] == "bullish"
        assert fvg["gap_bottom"] == 1080.0  # candle[0].high
        assert fvg["gap_top"] == 1090.0     # candle[2].low
        assert fvg["is_extreme"] == 1       # First FVG = extreme

    def test_bullish_fvg_rejected_outside_zone(self):
        """FVGs outside the parent zone should NOT be returned."""
        candles = make_candles([
            # FVG well above the zone_upper (1377.5)
            {"ts": "2020-01-01", "open": 1800, "high": 1850, "low": 1780, "close": 1830},
            {"ts": "2020-04-01", "open": 1830, "high": 1900, "low": 1825, "close": 1880},
            {"ts": "2020-07-01", "open": 1880, "high": 1950, "low": 1860, "close": 1920},
        ])

        fvgs = self.detector.detect_in_zone(
            candles, "3M",
            zone_upper=1377.5,
            zone_lower=680.0,
            direction="bullish",
        )

        assert len(fvgs) == 0

    # ── Bearish FVG detection ────────────────────────────────────────────────

    def test_bearish_fvg_detected(self):
        """Bearish FVG: candle[2].high < candle[0].low, within zone."""
        candles = make_candles([
            # Candle 0: low = 1500
            {"ts": "2020-01-01", "open": 1550, "high": 1580, "low": 1500, "close": 1520},
            # Candle 1: displacement (high must NOT go above candle[0].high = 1580)
            {"ts": "2020-04-01", "open": 1520, "high": 1570, "low": 1450, "close": 1460},
            # Candle 2: high = 1490 < candle[0].low = 1500 → FVG!
            {"ts": "2020-07-01", "open": 1460, "high": 1490, "low": 1430, "close": 1450},
        ])

        fvgs = self.detector.detect_in_zone(
            candles, "3M",
            zone_upper=1600.0,
            zone_lower=1400.0,
            direction="bearish",
        )

        assert len(fvgs) >= 1
        fvg = fvgs[0]
        assert fvg["direction"] == "bearish"
        assert fvg["gap_top"] == 1500.0     # candle[0].low
        assert fvg["gap_bottom"] == 1490.0  # candle[2].high

    # ── Wick rule enforcement ────────────────────────────────────────────────

    def test_wick_rule_bullish_rejects_sweep(self):
        """Bullish FVG should be rejected if C1 low sweeps below C0 low."""
        candles = make_candles([
            {"ts": "2015-01-01", "open": 1050, "high": 1080, "low": 1040, "close": 1060},
            # C1 low (1030) goes below C0 low (1040) — wick rule violation!
            {"ts": "2015-04-01", "open": 1060, "high": 1120, "low": 1030, "close": 1100},
            {"ts": "2015-07-01", "open": 1100, "high": 1150, "low": 1090, "close": 1130},
        ])

        fvgs = self.detector.detect_in_zone(
            candles, "3M",
            zone_upper=1377.5,
            zone_lower=680.0,
            direction="bullish",
        )

        assert len(fvgs) == 0  # Rejected by wick rule

    def test_wick_rule_bearish_rejects_sweep(self):
        """Bearish FVG should be rejected if C1 high sweeps above C0 high."""
        candles = make_candles([
            {"ts": "2020-01-01", "open": 1550, "high": 1580, "low": 1500, "close": 1520},
            # C1 high (1590) goes above C0 high (1580) — wick rule violation!
            {"ts": "2020-04-01", "open": 1520, "high": 1590, "low": 1450, "close": 1460},
            {"ts": "2020-07-01", "open": 1460, "high": 1490, "low": 1430, "close": 1450},
        ])

        fvgs = self.detector.detect_in_zone(
            candles, "3M",
            zone_upper=1600.0,
            zone_lower=1400.0,
            direction="bearish",
        )

        assert len(fvgs) == 0  # Rejected by wick rule

    # ── Extreme FVG flagging ─────────────────────────────────────────────────

    def test_only_first_fvg_is_extreme(self):
        """Only the first FVG in the zone should be flagged as extreme."""
        candles = make_candles([
            # FVG 1
            {"ts": "2015-01-01", "open": 1050, "high": 1080, "low": 1040, "close": 1060},
            {"ts": "2015-04-01", "open": 1060, "high": 1120, "low": 1055, "close": 1100},
            {"ts": "2015-07-01", "open": 1100, "high": 1150, "low": 1090, "close": 1130},
            # FVG 2 (also in zone)
            {"ts": "2015-10-01", "open": 1050, "high": 1070, "low": 1030, "close": 1060},
            {"ts": "2016-01-01", "open": 1060, "high": 1110, "low": 1055, "close": 1090},
            {"ts": "2016-04-01", "open": 1090, "high": 1130, "low": 1080, "close": 1120},
        ])

        fvgs = self.detector.detect_in_zone(
            candles, "3M",
            zone_upper=1377.5,
            zone_lower=680.0,
            direction="bullish",
        )

        extremes = [f for f in fvgs if f["is_extreme"] == 1]
        non_extremes = [f for f in fvgs if f["is_extreme"] == 0]

        assert len(extremes) == 1  # Only first is extreme
        if len(fvgs) > 1:
            assert len(non_extremes) == len(fvgs) - 1

    # ── Mitigation ──────────────────────────────────────────────────────────

    def test_bullish_fvg_mitigation(self):
        """Bullish FVG mitigated when close <= gap_bottom."""
        fvgs = [{
            "fvg_id": "test-001",
            "timeframe": "3M",
            "direction": "bullish",
            "ts_candle1": pd.Timestamp("2015-01-01", tz="UTC"),
            "ts_candle3": pd.Timestamp("2015-07-01", tz="UTC"),
            "gap_top": 1090.0,
            "gap_bottom": 1080.0,
            "gap_size": 10.0,
            "gap_size_pct": 0.92,
            "is_extreme": 1,
            "is_mitigated": 0,
            "ts_mitigated": None,
            "parent_fvg_id": None,
        }]

        candles = make_candles([
            {"ts": "2015-10-01", "open": 1100, "high": 1120, "low": 1090, "close": 1110},
            # Close at 1070 <= gap_bottom 1080 — mitigated!
            {"ts": "2016-01-01", "open": 1110, "high": 1115, "low": 1060, "close": 1070},
        ])

        result = self.detector.check_mitigation(fvgs, candles)
        assert result[0]["is_mitigated"] == 1
        assert result[0]["ts_mitigated"] is not None

    def test_fvg_not_mitigated_when_price_above(self):
        """Bullish FVG NOT mitigated if no close <= gap_bottom."""
        fvgs = [{
            "fvg_id": "test-002",
            "timeframe": "3M",
            "direction": "bullish",
            "ts_candle1": pd.Timestamp("2015-01-01", tz="UTC"),
            "ts_candle3": pd.Timestamp("2015-07-01", tz="UTC"),
            "gap_top": 1090.0,
            "gap_bottom": 1080.0,
            "gap_size": 10.0,
            "gap_size_pct": 0.92,
            "is_extreme": 1,
            "is_mitigated": 0,
            "ts_mitigated": None,
            "parent_fvg_id": None,
        }]

        candles = make_candles([
            {"ts": "2015-10-01", "open": 1100, "high": 1200, "low": 1090, "close": 1150},
            {"ts": "2016-01-01", "open": 1150, "high": 1250, "low": 1100, "close": 1200},
        ])

        result = self.detector.check_mitigation(fvgs, candles)
        assert result[0]["is_mitigated"] == 0

    # ── Edge cases ──────────────────────────────────────────────────────────

    def test_no_fvg_with_fewer_than_3_candles(self):
        """Should return empty list with fewer than 3 candles."""
        candles = make_candles([
            {"ts": "2015-01-01", "open": 1050, "high": 1080, "low": 1040, "close": 1060},
        ])

        fvgs = self.detector.detect_in_zone(
            candles, "3M",
            zone_upper=1377.5, zone_lower=680.0,
            direction="bullish",
        )

        assert len(fvgs) == 0

    def test_gap_of_single_tick_qualifies(self):
        """Even a 1-tick gap qualifies as FVG."""
        candles = make_candles([
            {"ts": "2015-01-01", "open": 1050, "high": 1080.00, "low": 1040, "close": 1060},
            {"ts": "2015-04-01", "open": 1060, "high": 1120,    "low": 1055, "close": 1100},
            # gap: low 1080.01 > candle[0] high 1080.00 = 0.01 gap
            {"ts": "2015-07-01", "open": 1100, "high": 1150,    "low": 1080.01, "close": 1130},
        ])

        fvgs = self.detector.detect_in_zone(
            candles, "3M",
            zone_upper=1377.5, zone_lower=680.0,
            direction="bullish",
        )

        assert len(fvgs) >= 1
        assert fvgs[0]["gap_size"] == pytest.approx(0.01, abs=0.001)
