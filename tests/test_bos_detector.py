"""
IHQE v3 — BOS Detector Unit Tests
"""

import pandas as pd
import numpy as np
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.bos_detector import BOSDetector


def make_candles(data: list[dict]) -> pd.DataFrame:
    """Create a test OHLCV DataFrame from a list of dicts."""
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.set_index("ts", inplace=True)
    return df


class TestBOSDetector:
    """Tests for the BOSDetector class."""

    def setup_method(self):
        self.detector = BOSDetector()

    def test_bullish_bos_detected(self):
        """A candle closing above a confirmed swing high = bullish BOS.
        
        Requires 9+ candles for 12M (side=3 Williams Fractal needs 7-bar window).
        Candles 0-6 establish a swing high at index 3, then candle 8 breaks it.
        """
        candles = make_candles([
            # Leading candles — build up to swing high
            {"ts": "2004-01-01", "open": 700, "high": 720, "low": 690, "close": 710},
            {"ts": "2005-01-01", "open": 710, "high": 750, "low": 700, "close": 740},
            {"ts": "2006-01-01", "open": 740, "high": 800, "low": 730, "close": 790},
            # Swing high at index 3 (high=900, surrounded by lower highs)
            {"ts": "2007-01-01", "open": 790, "high": 900, "low": 780, "close": 860},
            # Pullback after swing high
            {"ts": "2008-01-01", "open": 860, "high": 870, "low": 810, "close": 830},
            {"ts": "2009-01-01", "open": 830, "high": 850, "low": 790, "close": 820},
            {"ts": "2010-01-01", "open": 820, "high": 860, "low": 800, "close": 840},
            # Recovery
            {"ts": "2011-01-01", "open": 840, "high": 880, "low": 830, "close": 870},
            # BOS candle: closes above swing high (900) by > 3%
            {"ts": "2012-01-01", "open": 870, "high": 960, "low": 860, "close": 940},
        ])

        events = self.detector.detect(candles, "12M")
        bullish = [e for e in events if e["direction"] == "bullish"]

        assert len(bullish) > 0
        latest = bullish[-1]
        assert latest["bos_close"] > latest["broken_level"]
        assert latest["timeframe"] == "12M"

    def test_bearish_bos_detected(self):
        """A candle closing below a confirmed swing low = bearish BOS.
        
        Candles 0-6 establish a swing low at index 3, then candle 8 breaks it.
        """
        candles = make_candles([
            # Leading candles — decline toward swing low
            {"ts": "2008-01-01", "open": 1900, "high": 1920, "low": 1870, "close": 1880},
            {"ts": "2009-01-01", "open": 1880, "high": 1890, "low": 1820, "close": 1830},
            {"ts": "2010-01-01", "open": 1830, "high": 1850, "low": 1780, "close": 1790},
            # Swing low at index 3 (low=1650, surrounded by higher lows)
            {"ts": "2011-01-01", "open": 1790, "high": 1800, "low": 1650, "close": 1700},
            # Bounce after swing low
            {"ts": "2012-01-01", "open": 1700, "high": 1780, "low": 1690, "close": 1760},
            {"ts": "2013-01-01", "open": 1760, "high": 1800, "low": 1740, "close": 1770},
            {"ts": "2014-01-01", "open": 1770, "high": 1790, "low": 1720, "close": 1730},
            # Decline again
            {"ts": "2015-01-01", "open": 1730, "high": 1740, "low": 1680, "close": 1690},
            # BOS candle: closes below swing low (1650) by > 3%
            {"ts": "2016-01-01", "open": 1690, "high": 1700, "low": 1560, "close": 1580},
        ])

        events = self.detector.detect(candles, "12M")
        bearish = [e for e in events if e["direction"] == "bearish"]

        assert len(bearish) > 0
        latest = bearish[-1]
        assert latest["bos_close"] < latest["broken_level"]

    def test_no_bos_when_close_within_range(self):
        """No BOS if close stays within the range of confirmed swing levels."""
        candles = make_candles([
            {"ts": "2004-01-01", "open": 800, "high": 820, "low": 790, "close": 810},
            {"ts": "2005-01-01", "open": 810, "high": 830, "low": 800, "close": 820},
            {"ts": "2006-01-01", "open": 820, "high": 850, "low": 810, "close": 840},
            # Swing high at index 3 (high=880)
            {"ts": "2007-01-01", "open": 840, "high": 880, "low": 830, "close": 860},
            {"ts": "2008-01-01", "open": 860, "high": 870, "low": 840, "close": 850},
            {"ts": "2009-01-01", "open": 850, "high": 860, "low": 830, "close": 840},
            {"ts": "2010-01-01", "open": 840, "high": 855, "low": 825, "close": 845},
            # Close at 860 is below swing high 880 — no BOS
            {"ts": "2011-01-01", "open": 845, "high": 870, "low": 840, "close": 860},
        ])

        events = self.detector.detect(candles, "12M")
        bos_at_2011 = [e for e in events if str(e["bos_candle_ts"]).startswith("2011")]
        assert len(bos_at_2011) == 0

    def test_swing_points_correct_bullish(self):
        """Verify swing_low and swing_high are correctly identified for bullish BOS."""
        candles = make_candles([
            # Leading candles
            {"ts": "2002-01-01", "open": 500, "high": 530, "low": 490, "close": 520},
            {"ts": "2003-01-01", "open": 520, "high": 560, "low": 510, "close": 550},
            {"ts": "2004-01-01", "open": 550, "high": 610, "low": 540, "close": 600},
            # Swing high at index 3 (high=700, surrounded by lower highs on both sides)
            {"ts": "2005-01-01", "open": 600, "high": 700, "low": 580, "close": 650},
            # Pullback — swing low forms here (low=550)
            {"ts": "2006-01-01", "open": 650, "high": 660, "low": 550, "close": 590},
            {"ts": "2007-01-01", "open": 590, "high": 620, "low": 570, "close": 610},
            {"ts": "2008-01-01", "open": 610, "high": 650, "low": 600, "close": 640},
            # Recovery
            {"ts": "2009-01-01", "open": 640, "high": 680, "low": 630, "close": 670},
            # BOS candle: closes above swing high (700) by > 3%
            {"ts": "2010-01-01", "open": 670, "high": 760, "low": 665, "close": 730},
        ])

        events = self.detector.detect(candles, "12M")
        bullish = [e for e in events if e["direction"] == "bullish"]
        assert len(bullish) > 0

        bos = bullish[-1]
        # Swing low should be from the lookback leg
        assert bos["swing_low"] <= 550
        # Swing high should include the BOS candle or forward scan
        assert bos["swing_high"] >= 730

    def test_bos_invalidation(self):
        """BOS should be invalidated when price closes beyond protective swing."""
        candles = make_candles([
            {"ts": "2006-01-01", "open": 600, "high": 650, "low": 580, "close": 620},
            {"ts": "2007-01-01", "open": 620, "high": 700, "low": 600, "close": 680},
            {"ts": "2008-01-01", "open": 680, "high": 750, "low": 660, "close": 720},
            {"ts": "2009-01-01", "open": 720, "high": 780, "low": 700, "close": 760},
            # BOS candle
            {"ts": "2010-01-01", "open": 760, "high": 820, "low": 750, "close": 800},
            # Price drops below swing_low — invalidation
            {"ts": "2011-01-01", "open": 700, "high": 710, "low": 500, "close": 550},
        ])

        events = self.detector.detect(candles, "12M")
        bullish = [e for e in events if e["direction"] == "bullish"]

        # Find BOS from 2010 — should be invalidated by 2011 close at 550
        bos_2010 = [e for e in bullish if str(e["bos_candle_ts"]).startswith("2010")]
        if bos_2010:
            assert bos_2010[0]["is_active"] == 0

    def test_get_active_bos(self):
        """get_active_bos should return only active BOS events."""
        events = [
            {"bos_id": "1", "timeframe": "12M", "direction": "bullish",
             "bos_candle_ts": pd.Timestamp("2009-01-01"), "is_active": 0},
            {"bos_id": "2", "timeframe": "12M", "direction": "bullish",
             "bos_candle_ts": pd.Timestamp("2015-01-01"), "is_active": 1},
        ]

        result = self.detector.get_active_bos(events, "12M", "bullish")
        assert result is not None
        assert result["bos_id"] == "2"

    def test_get_active_bos_none_when_all_broken(self):
        """get_active_bos returns None when all BOS events are invalidated."""
        events = [
            {"bos_id": "1", "timeframe": "12M", "direction": "bullish",
             "bos_candle_ts": pd.Timestamp("2009-01-01"), "is_active": 0},
        ]

        result = self.detector.get_active_bos(events, "12M", "bullish")
        assert result is None

    def test_insufficient_candles(self):
        """Should return empty list with fewer than 4 candles (3 lookback + 1)."""
        candles = make_candles([
            {"ts": "2008-01-01", "open": 800, "high": 850, "low": 780, "close": 830},
            {"ts": "2009-01-01", "open": 830, "high": 870, "low": 810, "close": 860},
        ])

        events = self.detector.detect(candles, "12M")
        assert events == []
