"""
IHQE v3 — Walk-Forward Backtester

Simulates a live market feed by stepping through historical 1H candles
chronologically. Evaluates three independent cascade pipelines:
1. Macro Swing (12M -> 3M -> 1M)
2. Mid Swing (3M -> 1M -> W)
3. Scalp (4H -> 1H)

Executes independent Long and Short cascades simultaneously.
Results are logged to ihqe.trades and output to backtest_results.csv.
"""

import logging
import os
import sys
import uuid
import pandas as pd
import numpy as np
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from database.clickhouse_client import ClickHouseClient
from engine.fvg_detector import FVGDetector

logger = logging.getLogger(__name__)


class Backtester:
    def __init__(self):
        self.db = ClickHouseClient()
        self.fvg_detector = FVGDetector()
        
        # Load all OHLCV data
        self.dfs = {
            "12M": self.db.get_ohlcv("12M"),
            "3M": self.db.get_ohlcv("3M"),
            "1M": self.db.get_ohlcv("1M"),
            "W": self.db.get_ohlcv("W"),
            "4H": self.db.get_ohlcv("4H"),
            "1H": self.db.get_ohlcv("1H"),
        }
        
        # Load all BOS events
        self.bos_events = {
            "12M": self.db.query_df("SELECT * FROM ihqe.bos_events WHERE timeframe='12M' ORDER BY bos_candle_ts").to_dict("records"),
            "3M": self.db.query_df("SELECT * FROM ihqe.bos_events WHERE timeframe='3M' ORDER BY bos_candle_ts").to_dict("records"),
            "1M": self.db.query_df("SELECT * FROM ihqe.bos_events WHERE timeframe='1M' ORDER BY bos_candle_ts").to_dict("records"),
            "W": self.db.query_df("SELECT * FROM ihqe.bos_events WHERE timeframe='W' ORDER BY bos_candle_ts").to_dict("records"),
            "4H": self.db.query_df("SELECT * FROM ihqe.bos_events WHERE timeframe='4H' ORDER BY bos_candle_ts").to_dict("records"),
            "1H": self.db.query_df("SELECT * FROM ihqe.bos_events WHERE timeframe='1H' ORDER BY bos_candle_ts").to_dict("records"),
        }
        
        # Cascade configurations
        self.cascades = {
            "macro": ["12M", "3M", "1M", "1H"],
            "mid": ["3M", "1M"],
            "scalp": ["4H", "1H"]
        }
        
        # Active trades
        self.active_trades = []
        self.closed_trades = []
        self.fvg_cache = {}
        
        # Precompute BOS invalidation timestamps
        self.bos_invalidation_cache = {}
        print("Precomputing BOS invalidation times...")
        df_1h = self.dfs["1H"]
        closes_1h = df_1h["close"].values
        index_1h = df_1h.index
        
        for tf, events in self.bos_events.items():
            for e in events:
                bos_ts = pd.Timestamp(e["bos_candle_ts"])
                e["bos_candle_ts_pd"] = bos_ts  # PRE-PARSE to save loop time!
                
                idx_start = index_1h.searchsorted(bos_ts, side='right')
                post_closes = closes_1h[idx_start:]
                
                invalidation_ts = None
                if e["direction"] == "bullish":
                    invalid_indices = np.where(post_closes < e["swing_low"])[0]
                else:
                    invalid_indices = np.where(post_closes > e["swing_high"])[0]
                    
                if len(invalid_indices) > 0:
                    invalidation_ts = index_1h[idx_start + invalid_indices[0]]
                    
                self.bos_invalidation_cache[e["bos_id"]] = invalidation_ts
                
        # Precompute all raw FVGs and mitigations
        self.raw_fvgs = {}
        print("Precomputing raw FVGs and mitigations...")
        for tf, df in self.dfs.items():
            bull_raw = self.fvg_detector._detect_raw(df, tf, "bullish")
            bull_raw = self.fvg_detector.check_mitigation(bull_raw, df)
            
            bear_raw = self.fvg_detector._detect_raw(df, tf, "bearish")
            bear_raw = self.fvg_detector.check_mitigation(bear_raw, df)
            
            # Pre-parse timestamps for FVGs too
            for f in bull_raw + bear_raw:
                f["ts_candle3_pd"] = pd.Timestamp(f["ts_candle3"])
                if f.get("ts_mitigated"):
                    f["ts_mitigated_pd"] = pd.Timestamp(f["ts_mitigated"])
            
            def build_np(raw_list):
                return {
                    "ts3": np.array([f["ts_candle3_pd"].value for f in raw_list]),
                    "mitigated": np.array([f["ts_mitigated_pd"].value if f.get("ts_mitigated") else 9223372036854775807 for f in raw_list]),
                    "bottom": np.array([f["gap_bottom"] for f in raw_list]),
                    "top": np.array([f["gap_top"] for f in raw_list]),
                    "dicts": raw_list
                }
                
            self.raw_fvgs[tf] = {
                "bullish": build_np(bull_raw), 
                "bearish": build_np(bear_raw)
            }

    def get_active_bos(self, tf: str, direction: str, current_ts: pd.Timestamp) -> Optional[dict]:
        """Find the latest BOS for a given timeframe and direction that occurred at or before current_ts, and is not invalidated."""
        events = self.bos_events[tf]
        
        latest_bos = None
        for e in events:
            if e["bos_candle_ts_pd"] <= current_ts and e["direction"] == direction:
                latest_bos = e
            elif e["bos_candle_ts_pd"] > current_ts:
                break  # List is chronologically sorted, so we can break early!
                
        if not latest_bos:
            return None
            
        invalidation_ts = self.bos_invalidation_cache.get(latest_bos["bos_id"])
        if invalidation_ts and current_ts >= invalidation_ts:
            return None
            
        return latest_bos

    def build_grid(self, bos: dict) -> dict:
        """Build the Fibonacci grid from a BOS event."""
        swing_high = bos["swing_high"]
        swing_low = bos["swing_low"]
        diff = swing_high - swing_low
        
        if bos["direction"] == "bullish":
            return {
                "level_1_000": swing_high,
                "level_0_500": swing_high - (diff * 0.5),
                "level_0_000": swing_low,
                "direction": "bullish"
            }
        else:
            return {
                "level_1_000": swing_low,
                "level_0_500": swing_low + (diff * 0.5),
                "level_0_000": swing_high,
                "direction": "bearish"
            }

    def detect_fvgs(self, tf: str, direction: str, grid: dict, current_ts: pd.Timestamp) -> list[dict]:
        """Fetch precomputed FVGs up to current_ts that fall within the grid zone and are not yet mitigated."""
        data = self.raw_fvgs[tf][direction]
        ts_val = current_ts.value
        
        if direction == "bullish":
            zone_upper = grid["level_0_500"]
            zone_lower = grid["level_0_000"]
        else:
            zone_upper = grid["level_0_000"]
            zone_lower = grid["level_0_500"]
            
        # Vectorized check
        mask = (data["ts3"] <= ts_val) & (data["mitigated"] > ts_val) & (data["bottom"] >= zone_lower) & (data["top"] <= zone_upper)
        valid_indices = np.where(mask)[0]
        
        zone_fvgs = []
        found_extreme = False
        
        for i in valid_indices:
            f_copy = data["dicts"][i].copy()
            if not found_extreme:
                f_copy["is_extreme"] = 1
                found_extreme = True
            else:
                f_copy["is_extreme"] = 0
            zone_fvgs.append(f_copy)
            
        return zone_fvgs

    def run(self):
        print("\nStarting Walk-Forward Backtester...")
        
        df_1h = self.dfs["1H"]
        if df_1h.empty:
            print("No 1H data available.")
            return

        ts_list = df_1h.index
        n_steps = len(ts_list)
        
        # We track whether we already entered a trade for a specific BOS
        # so we don't fire multiple entries for the same setup.
        entered_setups = set()

        for i in range(1, n_steps - 1):
            current_ts = ts_list[i]
            current_close = df_1h["close"].iloc[i]
            current_high = df_1h["high"].iloc[i]
            current_low = df_1h["low"].iloc[i]
            next_open = df_1h["open"].iloc[i+1]
            
            # Print progress every 10%
            if i % (n_steps // 10) == 0:
                print(f"  Progress: {i/n_steps*100:.0f}% ({current_ts.strftime('%Y-%m-%d')})")
                
            # ── 1. Trade Management ─────────────────────────────────────
            active_next = []
            for t in self.active_trades:
                exit_price = None
                exit_reason = None
                
                if t["direction"] == "long":
                    if current_low <= t["stop_loss"]:
                        exit_price = t["stop_loss"]
                        exit_reason = "stop_loss"
                    elif current_high >= t["take_profit"]:
                        exit_price = t["take_profit"]
                        exit_reason = "take_profit"
                else: # short
                    if current_high >= t["stop_loss"]:
                        exit_price = t["stop_loss"]
                        exit_reason = "stop_loss"
                    elif current_low <= t["take_profit"]:
                        exit_price = t["take_profit"]
                        exit_reason = "take_profit"
                        
                if exit_price is not None:
                    t["exit_price"] = exit_price
                    t["exit_ts"] = current_ts
                    t["exit_reason"] = exit_reason
                    
                    if t["direction"] == "long":
                        pnl_pct = (exit_price - t["entry_price"]) / t["entry_price"] * 100
                    else:
                        pnl_pct = (t["entry_price"] - exit_price) / t["entry_price"] * 100
                        
                    t["pnl_pct"] = pnl_pct
                    self.closed_trades.append(t)
                else:
                    active_next.append(t)
                    
            self.active_trades = active_next
            
            # ── 2. Evaluate Cascades ────────────────────────────────────
            for cascade_name, tfs in self.cascades.items():
                for direction in ["bullish", "bearish"]:
                    trade_dir = "long" if direction == "bullish" else "short"
                    
                    # Gate 1: Anchor BOS
                    tf1 = tfs[0]
                    bos1 = self.get_active_bos(tf1, direction, current_ts)
                    if not bos1:
                        continue
                        
                    grid1 = self.build_grid(bos1)
                    
                    # Prevent entering the same macro setup multiple times
                    setup_key = f"{cascade_name}_{direction}_{bos1['bos_id']}"
                    if setup_key in entered_setups:
                        continue

                    # Gate 2: Middle FVG
                    tf2 = tfs[1]
                    fvgs2 = self.detect_fvgs(tf2, direction, grid1, current_ts)
                    if not fvgs2:
                        continue
                    
                    # For a 3-tier cascade, we need a 3rd gate. For 2-tier (scalp), Gate 3 is skipped.
                    entry_tf = tfs[-1]
                    entry_grid = None
                    
                    if len(tfs) == 3:
                        tf3 = tfs[2]
                        # Assume the FVG itself forms a sort of sub-grid or we use the T2 BOS?
                        # Wait, the rule says: 1M FVG formed inside 3M discount zone.
                        # What is the 3M discount zone? It's the Fib Grid of the 3M BOS!
                        # We need the active 3M BOS to get the 3M discount zone!
                        bos2 = self.get_active_bos(tf2, direction, current_ts)
                        if not bos2:
                            continue
                        grid2 = self.build_grid(bos2)
                        
                        fvgs3 = self.detect_fvgs(tf3, direction, grid2, current_ts)
                        if not fvgs3:
                            continue
                            
                        # Entry zone is the T3 (e.g. 1M) discount zone, so we need T3 BOS
                        bos3 = self.get_active_bos(tf3, direction, current_ts)
                        if not bos3:
                            continue
                        entry_grid = self.build_grid(bos3)
                        
                    else:
                        # 2-tier cascade (Scalp)
                        # Entry zone is the T2 discount zone
                        bos2 = self.get_active_bos(tf2, direction, current_ts)
                        if not bos2:
                            continue
                        entry_grid = self.build_grid(bos2)
                        
                    # ── Check Entry Condition ────────────────────────────────
                    # Price must cross into the entry_grid's discount zone
                    trigger = False
                    if direction == "bullish":
                        if current_close <= entry_grid["level_0_500"]:
                            trigger = True
                    else:
                        if current_close >= entry_grid["level_0_500"]:
                            trigger = True
                            
                    if trigger:
                        # FIRE EXECUTION
                        raw_entry = float(next_open)
                        if direction == "bullish":
                            entry_price = raw_entry + 0.40
                        else:
                            entry_price = raw_entry - 0.40
                        
                        if direction == "bullish":
                            stop_loss = float(entry_grid["level_0_000"])  # Swing low of entry TF
                            take_profit = float(grid1["level_1_000"])     # Swing high of anchor TF
                            
                            # Invalid entry if price is already below SL
                            if entry_price <= stop_loss:
                                continue
                        else:
                            stop_loss = float(entry_grid["level_0_000"])  # Swing high of entry TF
                            take_profit = float(grid1["level_1_000"])     # Swing low of anchor TF
                            
                            if entry_price >= stop_loss:
                                continue
                                
                        # Calculate R:R
                        risk = abs(entry_price - stop_loss)
                        reward = abs(take_profit - entry_price)
                        rr = reward / risk if risk > 0 else 0
                        
                        self.active_trades.append({
                            "trade_id": str(uuid.uuid4()),
                            "trade_type": cascade_name,
                            "direction": trade_dir,
                            "timeframe": entry_tf,
                            "entry_ts": ts_list[i+1],  # Enter on next candle open
                            "entry_price": entry_price,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "rr_ratio": rr,
                            "exit_ts": None,
                            "exit_price": None,
                            "exit_reason": None,
                            "pnl_pct": None,
                        })
                        
                        entered_setups.add(setup_key)
                        
        self._report_results()

    def _report_results(self):
        print("\n============================================")
        print("  Walk-Forward Backtest Complete")
        print("============================================\n")
        
        all_trades = self.closed_trades + self.active_trades
        
        # Export to CSV
        df = pd.DataFrame(all_trades)
        if not df.empty:
            df.to_csv("backtest_results.csv", index=False)
            print(f"Results exported to backtest_results.csv ({len(all_trades)} trades)\n")
        
        for cname in ["macro", "mid", "scalp"]:
            c_trades = [t for t in all_trades if t["trade_type"] == cname]
            closed = [t for t in c_trades if t["exit_price"] is not None]
            
            wins = [t for t in closed if t["pnl_pct"] > 0]
            losses = [t for t in closed if t["pnl_pct"] <= 0]
            
            win_rate = (len(wins) / len(closed) * 100) if closed else 0
            avg_rr = np.mean([t["rr_ratio"] for t in closed]) if closed else 0
            total_pnl = sum(t["pnl_pct"] for t in closed)
            
            print(f"[{cname.upper()} CASCADE]")
            print(f"  Total Trades: {len(c_trades)}")
            print(f"  Closed: {len(closed)} (Wins: {len(wins)}, Losses: {len(losses)})")
            print(f"  Win Rate: {win_rate:.1f}%")
            print(f"  Avg R:R: {avg_rr:.2f}")
            print(f"  Total Return: {total_pnl:.2f}%\n")


if __name__ == "__main__":
    b = Backtester()
    b.run()
