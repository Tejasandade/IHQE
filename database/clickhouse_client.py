"""
ClickHouse database client wrapper for IHQE v3.
Provides typed methods for all table operations with retry logic.
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError, NetworkError

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import settings

logger = logging.getLogger(__name__)


class ClickHouseClient:
    """Lazy-connecting ClickHouse client with automatic retry logic."""

    MAX_RETRIES = 3
    RETRY_BACKOFF = 2  # seconds

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self._host = host or settings.CH_HOST
        self._port = port or settings.CH_PORT
        self._database = database or settings.CH_DATABASE
        self._user = user or settings.CH_USER
        self._password = password or settings.CH_PASSWORD
        self._client: Optional[Client] = None

    def _connect(self) -> Client:
        """Lazy connection — only connects on first use."""
        if self._client is None:
            logger.info(
                f"Connecting to ClickHouse at {self._host}:{self._port}/{self._database}"
            )
            self._client = Client(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._user,
                password=self._password,
                settings={"use_numpy": False},
            )
        return self._client

    def _execute_with_retry(self, operation: str, func, *args, **kwargs):
        """Execute a function with retry logic on ClickHouse errors."""
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                client = self._connect()
                return func(client, *args, **kwargs)
            except (NetworkError, ConnectionError, OSError) as e:
                last_error = e
                logger.warning(
                    f"{operation} attempt {attempt}/{self.MAX_RETRIES} failed: {e}"
                )
                self._client = None  # Force reconnect
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_BACKOFF * attempt)
            except ClickHouseError as e:
                logger.error(f"{operation} ClickHouse error: {e}")
                raise
        raise ConnectionError(
            f"{operation} failed after {self.MAX_RETRIES} retries: {last_error}"
        )

    # ── Query Methods ────────────────────────────────────────────────────────

    def query_df(self, sql: str, params: Optional[dict] = None) -> pd.DataFrame:
        """Execute a SQL query and return results as a Pandas DataFrame."""
        def _run(client: Client):
            result = client.execute(sql, params or {}, with_column_types=True)
            rows, columns = result
            col_names = [c[0] for c in columns]
            return pd.DataFrame(rows, columns=col_names)

        return self._execute_with_retry("query_df", _run)

    def execute(self, sql: str, params: Optional[dict] = None):
        """Execute a SQL statement (INSERT, CREATE, etc.)."""
        def _run(client: Client):
            return client.execute(sql, params or {})

        return self._execute_with_retry("execute", _run)

    # ── Tick Operations ──────────────────────────────────────────────────────

    def insert_ticks(self, rows: list[dict]) -> int:
        """Bulk insert tick rows into xauusd_ticks.
        
        Each row must have: ts, bid, ask, source (optional, defaults to 'tiingo')
        Returns number of rows inserted.
        """
        if not rows:
            return 0

        def _run(client: Client):
            client.execute(
                "INSERT INTO ihqe.xauusd_ticks (ts, bid, ask, source) VALUES",
                [
                    {
                        "ts": r["ts"],
                        "bid": r["bid"],
                        "ask": r["ask"],
                        "source": r.get("source", "tiingo"),
                    }
                    for r in rows
                ],
            )
            return len(rows)

        return self._execute_with_retry("insert_ticks", _run)

    def get_latest_tick_ts(self) -> Optional[datetime]:
        """Returns the most recent tick timestamp, or None if table is empty."""
        df = self.query_df("SELECT max(ts) as max_ts FROM ihqe.xauusd_ticks")
        if df.empty or df.iloc[0]["max_ts"] is None:
            return None
        val = df.iloc[0]["max_ts"]
        if isinstance(val, datetime):
            return val
        return None

    def get_tick_ts_range(self) -> tuple[Optional[datetime], Optional[datetime]]:
        """Returns (min_ts, max_ts) of ticks in the database."""
        df = self.query_df(
            "SELECT min(ts) as min_ts, max(ts) as max_ts FROM ihqe.xauusd_ticks"
        )
        if df.empty:
            return None, None
        min_ts = df.iloc[0]["min_ts"]
        max_ts = df.iloc[0]["max_ts"]
        if not isinstance(min_ts, datetime):
            min_ts = None
        if not isinstance(max_ts, datetime):
            max_ts = None
        return min_ts, max_ts

    # ── OHLCV Operations ─────────────────────────────────────────────────────

    def insert_ohlcv(self, timeframe: str, rows: list[dict]) -> int:
        """Bulk insert OHLCV rows for a specific timeframe.
        
        Each row must have: ts, open, high, low, close, tick_count (optional)
        """
        if not rows:
            return 0

        def _run(client: Client):
            client.execute(
                "INSERT INTO ihqe.xauusd_ohlcv (timeframe, ts, open, high, low, close, tick_count) VALUES",
                [
                    {
                        "timeframe": timeframe,
                        "ts": r["ts"],
                        "open": r["open"],
                        "high": r["high"],
                        "low": r["low"],
                        "close": r["close"],
                        "tick_count": r.get("tick_count", 0),
                    }
                    for r in rows
                ],
            )
            return len(rows)

        return self._execute_with_retry("insert_ohlcv", _run)

    def get_ohlcv(
        self, timeframe: str, start: Optional[str] = None, end: Optional[str] = None
    ) -> pd.DataFrame:
        """Retrieve OHLCV data for a timeframe, optionally filtered by date range."""
        conditions = ["timeframe = %(tf)s"]
        params = {"tf": timeframe}

        if start:
            conditions.append("ts >= %(start)s")
            params["start"] = start
        if end and end != "today":
            conditions.append("ts <= %(end)s")
            params["end"] = end

        where = " AND ".join(conditions)
        sql = f"SELECT ts, open, high, low, close, tick_count FROM ihqe.xauusd_ohlcv WHERE {where} ORDER BY ts"
        df = self.query_df(sql, params)
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df.set_index("ts", inplace=True)
        return df

    def delete_ohlcv(self, timeframe: str) -> None:
        """Delete all OHLCV data for a specific timeframe (for rebuilds)."""
        self.execute(
            "ALTER TABLE ihqe.xauusd_ohlcv DELETE WHERE timeframe = %(tf)s",
            {"tf": timeframe},
        )
        logger.info(f"Deleted OHLCV data for timeframe {timeframe}")

    # ── BOS Event Operations ─────────────────────────────────────────────────

    def insert_bos_events(self, rows: list[dict]) -> int:
        """Bulk insert BOS event rows."""
        if not rows:
            return 0

        def _run(client: Client):
            client.execute(
                """INSERT INTO ihqe.bos_events 
                (bos_id, timeframe, direction, bos_candle_ts,
                 broken_level, bos_close, swing_low, swing_low_ts, swing_high, swing_high_ts, is_active) VALUES""",
                [
                    {
                        "bos_id": r.get("bos_id", str(uuid.uuid4())),
                        "timeframe": r["timeframe"],
                        "direction": r["direction"],
                        "bos_candle_ts": r["bos_candle_ts"],
                        "broken_level": r["broken_level"],
                        "bos_close": r["bos_close"],
                        "swing_low": r["swing_low"],
                        "swing_low_ts": r.get("swing_low_ts", r["bos_candle_ts"]),
                        "swing_high": r["swing_high"],
                        "swing_high_ts": r.get("swing_high_ts", r["bos_candle_ts"]),
                        "is_active": r.get("is_active", 1),
                    }
                    for r in rows
                ],
            )
            return len(rows)

        return self._execute_with_retry("insert_bos_events", _run)

    def get_bos_events(
        self, timeframe: str, direction: Optional[str] = None,
        active_only: bool = False, as_of_ts: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Retrieve BOS events for a timeframe."""
        conditions = ["timeframe = %(tf)s"]
        params: dict = {"tf": timeframe}
        if direction:
            conditions.append("direction = %(dir)s")
            params["dir"] = direction
        if active_only:
            conditions.append("is_active = 1")
        if as_of_ts:
            conditions.append("bos_candle_ts <= %(as_of_ts)s")
            params["as_of_ts"] = as_of_ts

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM ihqe.bos_events FINAL WHERE {where} ORDER BY bos_candle_ts"
        return self.query_df(sql, params)

    def clear_bos_events(self, timeframe: Optional[str] = None) -> None:
        """Clear BOS events, optionally for a specific timeframe."""
        if timeframe:
            self.execute(
                "ALTER TABLE ihqe.bos_events DELETE WHERE timeframe = %(tf)s",
                {"tf": timeframe},
            )
        else:
            self.execute("TRUNCATE TABLE ihqe.bos_events")

    def get_latest_structure_ts(self, timeframe: str) -> Optional[str]:
        """Get the timestamp of the most recent BOS event for a timeframe."""
        df = self.query_df(
            "SELECT max(bos_candle_ts) as max_ts FROM ihqe.bos_events WHERE timeframe = %(tf)s",
            {"tf": timeframe}
        )
        if not df.empty and pd.notna(df.iloc[0]["max_ts"]):
            return str(df.iloc[0]["max_ts"])
        return None

    # ── FVG Operations ───────────────────────────────────────────────────────

    def insert_fvg_events(self, rows: list[dict]) -> int:
        """Bulk insert FVG event rows."""
        if not rows:
            return 0

        def _run(client: Client):
            client.execute(
                """INSERT INTO ihqe.fvg_events 
                (fvg_id, timeframe, direction, ts_candle1, ts_candle3, 
                 gap_top, gap_bottom, gap_size, gap_size_pct, 
                 is_extreme, is_mitigated, ts_mitigated, parent_fvg_id) VALUES""",
                [
                    {
                        "fvg_id": r.get("fvg_id", str(uuid.uuid4())),
                        "timeframe": r["timeframe"],
                        "direction": r["direction"],
                        "ts_candle1": r["ts_candle1"],
                        "ts_candle3": r["ts_candle3"],
                        "gap_top": r["gap_top"],
                        "gap_bottom": r["gap_bottom"],
                        "gap_size": r["gap_size"],
                        "gap_size_pct": r["gap_size_pct"],
                        "is_extreme": r.get("is_extreme", 0),
                        "is_mitigated": r.get("is_mitigated", 0),
                        "ts_mitigated": r.get("ts_mitigated"),
                        "parent_fvg_id": r.get("parent_fvg_id"),
                    }
                    for r in rows
                ],
            )
            return len(rows)

        return self._execute_with_retry("insert_fvg_events", _run)

    def get_fvg_events(
        self, timeframe: str, direction: Optional[str] = None,
        as_of_ts: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Retrieve FVG events for a timeframe."""
        conditions = ["timeframe = %(tf)s"]
        params: dict = {"tf": timeframe}
        if direction:
            conditions.append("direction = %(dir)s")
            params["dir"] = direction
        if as_of_ts:
            conditions.append("ts_candle3 <= %(as_of_ts)s")
            params["as_of_ts"] = as_of_ts

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM ihqe.fvg_events FINAL WHERE {where} ORDER BY ts_candle1"
        return self.query_df(sql, params)

    def clear_fvg_events(self, timeframe: Optional[str] = None) -> None:
        """Clear FVG events, optionally for a specific timeframe."""
        if timeframe:
            self.execute(
                "ALTER TABLE ihqe.fvg_events DELETE WHERE timeframe = %(tf)s",
                {"tf": timeframe},
            )
        else:
            self.execute("TRUNCATE TABLE ihqe.fvg_events")

    # ── Fibonacci Grid Operations ────────────────────────────────────────────

    def insert_fib_grids(self, rows: list[dict]) -> int:
        """Bulk insert Fibonacci grid rows."""
        if not rows:
            return 0

        def _run(client: Client):
            client.execute(
                """INSERT INTO ihqe.fib_grids 
                (grid_id, timeframe, direction, anchor_event_id,
                 swing_low_ts, swing_high_ts, swing_low, swing_high, total_range,
                 level_1_000, level_0_786, level_0_618, level_0_500,
                 level_0_382, level_0_236, level_0_000,
                 is_active, parent_grid_id) VALUES""",
                [
                    {
                        "grid_id": r.get("grid_id", str(uuid.uuid4())),
                        "timeframe": r["timeframe"],
                        "direction": r["direction"],
                        "anchor_event_id": r["anchor_event_id"],
                        "swing_low_ts": r["swing_low_ts"],
                        "swing_high_ts": r["swing_high_ts"],
                        "swing_low": r["swing_low"],
                        "swing_high": r["swing_high"],
                        "total_range": r["total_range"],
                        "level_1_000": r["level_1_000"],
                        "level_0_786": r["level_0_786"],
                        "level_0_618": r["level_0_618"],
                        "level_0_500": r["level_0_500"],
                        "level_0_382": r["level_0_382"],
                        "level_0_236": r["level_0_236"],
                        "level_0_000": r["level_0_000"],
                        "is_active": r.get("is_active", 1),
                        "parent_grid_id": r.get("parent_grid_id"),
                    }
                    for r in rows
                ],
            )
            return len(rows)

        return self._execute_with_retry("insert_fib_grids", _run)

    def get_fib_grids(
        self,
        timeframe: str,
        direction: Optional[str] = None,
        active_only: bool = False,
        as_of_ts: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Retrieve Fibonacci grids for a timeframe."""
        conditions = ["timeframe = %(tf)s"]
        params: dict = {"tf": timeframe}
        if direction:
            conditions.append("direction = %(dir)s")
            params["dir"] = direction
        if active_only:
            conditions.append("is_active = 1")
        if as_of_ts:
            conditions.append("swing_low_ts <= %(as_of_ts)s")
            conditions.append("swing_high_ts <= %(as_of_ts)s")
            params["as_of_ts"] = as_of_ts

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM ihqe.fib_grids FINAL WHERE {where} ORDER BY swing_low_ts"
        return self.query_df(sql, params)

    def clear_fib_grids(self, timeframe: Optional[str] = None) -> None:
        """Clear Fibonacci grids, optionally for a specific timeframe."""
        if timeframe:
            self.execute(
                "ALTER TABLE ihqe.fib_grids DELETE WHERE timeframe = %(tf)s",
                {"tf": timeframe},
            )
        else:
            self.execute("TRUNCATE TABLE ihqe.fib_grids")

    # ── Cascade State Operations ─────────────────────────────────────────────

    def insert_cascade_states(self, rows: list[dict]) -> int:
        """Bulk insert cascade state rows."""
        if not rows:
            return 0

        def _run(client: Client):
            client.execute(
                """INSERT INTO ihqe.cascade_states 
                (state_id, cascade_type, direction, timeframe, gate_status,
                 confirmed_at, fvg_id, grid_id, layer, ts_updated) VALUES""",
                [
                    {
                        "state_id": r.get("state_id", str(uuid.uuid4())),
                        "cascade_type": r["cascade_type"],
                        "direction": r["direction"],
                        "timeframe": r["timeframe"],
                        "gate_status": r["gate_status"],
                        "confirmed_at": r.get("confirmed_at"),
                        "fvg_id": r.get("fvg_id"),
                        "grid_id": r.get("grid_id"),
                        "layer": r.get("layer", "swing"),
                        "ts_updated": r["ts_updated"],
                    }
                    for r in rows
                ],
            )
            return len(rows)

        return self._execute_with_retry("insert_cascade_states", _run)

    def get_cascade_states(
        self, layer: Optional[str] = None, direction: Optional[str] = None,
        as_of_ts: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Retrieve cascade states, optionally filtered by layer and direction."""
        conditions = []
        params: dict = {}
        if layer:
            conditions.append("layer = %(layer)s")
            params["layer"] = layer
        if direction:
            conditions.append("direction = %(dir)s")
            params["dir"] = direction
        if as_of_ts:
            conditions.append("ts_updated <= %(as_of_ts)s")
            params["as_of_ts"] = as_of_ts

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM ihqe.cascade_states WHERE {where} ORDER BY ts_updated DESC LIMIT 1 BY cascade_type, direction, timeframe"
        return self.query_df(sql, params)

    def clear_cascade_states(self) -> None:
        """Clear all cascade states."""
        self.execute("TRUNCATE TABLE ihqe.cascade_states")

    # ── Trade Signal Operations ──────────────────────────────────────────────

    def insert_trade_signals(self, rows: list[dict]) -> int:
        """Bulk insert trade signal rows."""
        if not rows:
            return 0

        def _run(client: Client):
            client.execute(
                """INSERT INTO ihqe.trade_signals 
                (signal_id, signal_type, trade_type, direction, gates_confirmed,
                 target_upper, target_lower, linked_signal_id, published_at, status) VALUES""",
                [
                    {
                        "signal_id": r.get("signal_id", str(uuid.uuid4())),
                        "signal_type": r["signal_type"],
                        "trade_type": r["trade_type"],
                        "direction": r["direction"],
                        "gates_confirmed": r["gates_confirmed"],
                        "target_upper": r["target_upper"],
                        "target_lower": r["target_lower"],
                        "linked_signal_id": r.get("linked_signal_id"),
                        "published_at": r["published_at"],
                        "status": r.get("status", "open"),
                    }
                    for r in rows
                ],
            )
            return len(rows)

        return self._execute_with_retry("insert_trade_signals", _run)

    def get_trade_signals(
        self, trade_type: Optional[str] = None, status: Optional[str] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """Retrieve trade signals with optional filters."""
        conditions = []
        params: dict = {}
        if trade_type:
            conditions.append("trade_type = %(tt)s")
            params["tt"] = trade_type
        if status:
            conditions.append("status = %(st)s")
            params["st"] = status

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM ihqe.trade_signals WHERE {where} ORDER BY published_at DESC LIMIT {limit}"
        return self.query_df(sql, params)

    def clear_trade_signals(self) -> None:
        """Clear all trade signals."""
        self.execute("TRUNCATE TABLE ihqe.trade_signals")

    # ── Trade Operations ─────────────────────────────────────────────────────

    def insert_trades(self, rows: list[dict]) -> int:
        """Bulk insert trade rows."""
        if not rows:
            return 0

        def _run(client: Client):
            client.execute(
                """INSERT INTO ihqe.trades
                (trade_id, signal_id, trade_type, direction, timeframe,
                 entry_price, stop_loss, take_profit, entry_ts,
                 exit_price, exit_ts, exit_reason, pnl_pct, status) VALUES""",
                [
                    {
                        "trade_id": r.get("trade_id", str(uuid.uuid4())),
                        "signal_id": r["signal_id"],
                        "trade_type": r["trade_type"],
                        "direction": r["direction"],
                        "timeframe": r["timeframe"],
                        "entry_price": r["entry_price"],
                        "stop_loss": r["stop_loss"],
                        "take_profit": r["take_profit"],
                        "entry_ts": r["entry_ts"],
                        "exit_price": r.get("exit_price"),
                        "exit_ts": r.get("exit_ts"),
                        "exit_reason": r.get("exit_reason", ""),
                        "pnl_pct": r.get("pnl_pct"),
                        "status": r.get("status", "open"),
                    }
                    for r in rows
                ],
            )
            return len(rows)

        return self._execute_with_retry("insert_trades", _run)

    def get_trades(
        self, trade_type: Optional[str] = None, status: Optional[str] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """Retrieve trades with optional filters."""
        conditions = []
        params: dict = {}
        if trade_type:
            conditions.append("trade_type = %(tt)s")
            params["tt"] = trade_type
        if status:
            conditions.append("status = %(st)s")
            params["st"] = status

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM ihqe.trades WHERE {where} ORDER BY entry_ts DESC LIMIT {limit}"
        return self.query_df(sql, params)

    def clear_trades(self) -> None:
        """Clear all trades."""
        self.execute("TRUNCATE TABLE ihqe.trades")

    # ── Utility ──────────────────────────────────────────────────────────────

    def table_count(self, table: str) -> int:
        """Get row count for a table."""
        df = self.query_df(f"SELECT count() as c FROM ihqe.{table}")
        return int(df.iloc[0]["c"]) if not df.empty else 0

    def close(self):
        """Close the connection."""
        if self._client:
            self._client.disconnect()
            self._client = None
            logger.info("ClickHouse connection closed")
