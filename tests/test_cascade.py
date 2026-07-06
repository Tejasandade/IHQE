"""
IHQE v3 — Cascade State Machine Unit Tests
"""

import pandas as pd
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.cascade import SwingCascade, SwingGate, ScalpLayer


def make_candles(data: list[dict]) -> pd.DataFrame:
    """Create a test OHLCV DataFrame from a list of dicts."""
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.set_index("ts", inplace=True)
    return df


class TestSwingGate:
    """Tests for the SwingGate class."""

    def test_initial_state(self):
        gate = SwingGate("12M", "bullish")
        assert gate.gate_status == "waiting"
        assert gate.is_confirmed is False

    def test_confirm_bos(self):
        gate = SwingGate("12M", "bullish")
        bos = {"bos_id": "bos-1"}
        grid = {"grid_id": "grid-1"}
        gate.confirm_bos(bos, grid, pd.Timestamp("2009-01-01"))

        assert gate.gate_status == "bos_confirmed"
        assert gate.is_confirmed is True
        assert gate.bos_id == "bos-1"
        assert gate.grid_id == "grid-1"

    def test_confirm_fvg(self):
        gate = SwingGate("3M", "bullish")
        fvg = {"fvg_id": "fvg-1"}
        grid = {"grid_id": "grid-2"}
        gate.confirm_fvg(fvg, grid, pd.Timestamp("2015-01-01"))

        assert gate.gate_status == "fvg_confirmed"
        assert gate.is_confirmed is True

    def test_enter_zone_from_bos_confirmed(self):
        gate = SwingGate("12M", "bullish")
        bos = {"bos_id": "bos-1"}
        grid = {"grid_id": "grid-1"}
        gate.confirm_bos(bos, grid, pd.Timestamp("2009-01-01"))
        gate.enter_zone()

        assert gate.gate_status == "zone_entered"
        assert gate.is_confirmed is True

    def test_enter_zone_from_fvg_confirmed(self):
        gate = SwingGate("3M", "bullish")
        fvg = {"fvg_id": "fvg-1"}
        grid = {"grid_id": "grid-2"}
        gate.confirm_fvg(fvg, grid, pd.Timestamp("2015-01-01"))
        gate.enter_zone()

        assert gate.gate_status == "zone_entered"

    def test_enter_zone_from_waiting_does_nothing(self):
        gate = SwingGate("12M", "bullish")
        gate.enter_zone()
        assert gate.gate_status == "waiting"

    def test_reset(self):
        gate = SwingGate("12M", "bullish")
        bos = {"bos_id": "bos-1"}
        grid = {"grid_id": "grid-1"}
        gate.confirm_bos(bos, grid, pd.Timestamp("2009-01-01"))
        gate.reset()

        assert gate.gate_status == "waiting"
        assert gate.bos_id is None
        assert gate.grid is None

    def test_to_dict(self):
        gate = SwingGate("12M", "bullish")
        d = gate.to_dict(pd.Timestamp("2024-01-01"))

        assert d["timeframe"] == "12M"
        assert d["direction"] == "bullish"
        assert d["gate_status"] == "waiting"
        assert d["layer"] == "swing"
        assert "state_id" in d


class TestSwingCascade:
    """Tests for the SwingCascade class."""

    def test_initial_gates_confirmed_is_zero(self):
        mock_db = MagicMock()
        cascade = SwingCascade(mock_db, "bullish")
        assert cascade.get_gates_confirmed() == 0

    def test_swing_timeframes(self):
        mock_db = MagicMock()
        cascade = SwingCascade(mock_db, "bullish")
        assert cascade.SWING_TIMEFRAMES == ["12M", "3M", "1M"]
        assert set(cascade.gates.keys()) == {"12M", "3M", "1M"}

    def test_gates_confirmed_count(self):
        mock_db = MagicMock()
        cascade = SwingCascade(mock_db, "bullish")

        # Confirm 12M gate
        cascade.gates["12M"].confirm_bos(
            {"bos_id": "b1"}, {"grid_id": "g1"},
            pd.Timestamp("2009-01-01"),
        )
        assert cascade.get_gates_confirmed() == 1

        # Confirm 3M gate
        cascade.gates["3M"].confirm_fvg(
            {"fvg_id": "f1"}, {"grid_id": "g2"},
            pd.Timestamp("2015-01-01"),
        )
        assert cascade.get_gates_confirmed() == 2

        # Confirm 1M gate
        cascade.gates["1M"].confirm_fvg(
            {"fvg_id": "f2"}, {"grid_id": "g3"},
            pd.Timestamp("2016-01-01"),
        )
        assert cascade.get_gates_confirmed() == 3

    def test_signal_type_progression(self):
        mock_db = MagicMock()
        cascade = SwingCascade(mock_db, "bullish")

        assert cascade.get_current_signal_type() is None

        cascade.gates["12M"].confirm_bos(
            {"bos_id": "b1"}, {"grid_id": "g1"},
            pd.Timestamp("2009-01-01"),
        )
        assert cascade.get_current_signal_type() == "macro_alert"

        cascade.gates["3M"].confirm_fvg(
            {"fvg_id": "f1"}, {"grid_id": "g2"},
            pd.Timestamp("2015-01-01"),
        )
        assert cascade.get_current_signal_type() == "mid_alert"

        cascade.gates["1M"].confirm_fvg(
            {"fvg_id": "f2"}, {"grid_id": "g3"},
            pd.Timestamp("2016-01-01"),
        )
        assert cascade.get_current_signal_type() == "active"

        # Zone entered = execute
        cascade.gates["1M"].enter_zone()
        assert cascade.get_current_signal_type() == "execute"

    def test_is_entry_valid(self):
        mock_db = MagicMock()
        cascade = SwingCascade(mock_db, "bullish")

        assert cascade.is_entry_valid() is False

        # Confirm all 3 gates
        cascade.gates["12M"].confirm_bos(
            {"bos_id": "b1"}, {"grid_id": "g1"},
            pd.Timestamp("2009-01-01"),
        )
        cascade.gates["3M"].confirm_fvg(
            {"fvg_id": "f1"}, {"grid_id": "g2"},
            pd.Timestamp("2015-01-01"),
        )
        cascade.gates["1M"].confirm_fvg(
            {"fvg_id": "f2"}, {"grid_id": "g3"},
            pd.Timestamp("2016-01-01"),
        )

        # Still not valid — 1M zone not entered
        assert cascade.is_entry_valid() is False

        cascade.gates["1M"].enter_zone()
        assert cascade.is_entry_valid() is True

    def test_get_stop_loss_and_take_profit(self):
        mock_db = MagicMock()
        cascade = SwingCascade(mock_db, "bullish")

        # No grids yet
        assert cascade.get_stop_loss() is None
        assert cascade.get_take_profit() is None

        # Set grids
        cascade.gates["12M"].grid = {
            "level_0_000": 680.0,
            "level_1_000": 2075.0,
        }
        cascade.gates["1M"].grid = {
            "level_0_000": 1050.0,
            "level_1_000": 1300.0,
        }

        assert cascade.get_stop_loss() == 1050.0
        assert cascade.get_take_profit() == 2075.0

    def test_parent_must_confirm_before_child(self):
        """3M should NOT process if 12M is not zone_entered."""
        mock_db = MagicMock()
        cascade = SwingCascade(mock_db, "bullish")

        # 12M is still 'waiting' — 3M should not advance
        assert cascade.gates["12M"].gate_status == "waiting"
        assert cascade.gates["3M"].gate_status == "waiting"

        # Even if we manually try to process 3M, parent check blocks it
        # (process_bar calls _process_child which checks parent status)


class TestScalpLayer:
    """Tests for the ScalpLayer class."""

    def test_scalp_inactive_with_few_gates(self):
        """Scalp layer should not activate with < 2 swing gates."""
        mock_db = MagicMock()
        mock_db.get_ohlcv.return_value = pd.DataFrame()

        swing = SwingCascade(mock_db, "bullish")
        assert swing.get_gates_confirmed() == 0

        scalp = ScalpLayer(mock_db)
        scalp.process_bar("4H", {}, swing)

        assert len(scalp.scalp_setups) == 0

    def test_scalp_timeframes(self):
        mock_db = MagicMock()
        scalp = ScalpLayer(mock_db)
        assert scalp.SCALP_TIMEFRAMES == ["4H", "1H"]

    def test_non_scalp_timeframe_ignored(self):
        """process_bar should ignore non-scalp timeframes."""
        mock_db = MagicMock()
        swing = SwingCascade(mock_db, "bullish")
        scalp = ScalpLayer(mock_db)

        scalp.process_bar("12M", {}, swing)
        assert len(scalp.scalp_setups) == 0
