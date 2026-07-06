import time
from collections import deque
from typing import Dict, Any, Optional

class QuoteImbalanceDetector:
    def __init__(self):
        # Store tuples of (timestamp, is_ask_up, is_bid_up)
        # is_ask_up and is_bid_up are booleans
        self.tick_history = deque()
        self.window_seconds = 60.0
        self.imbalance_threshold = 0.65
        
        self.last_ask = None
        self.last_bid = None

    def process_tick(self, bid: float, ask: float, timestamp: float = None) -> Optional[Dict[str, Any]]:
        """
        Process a new quote tick.
        Returns a dictionary with the event if an imbalance is detected, else None.
        """
        now = timestamp if timestamp is not None else time.time()
        
        # Determine tick direction
        is_ask_up = False
        is_bid_up = False
        
        if self.last_ask is not None and ask > self.last_ask:
            is_ask_up = True
            
        if self.last_bid is not None and bid > self.last_bid:
            is_bid_up = True
            
        self.last_ask = ask
        self.last_bid = bid
        
        # We only record ticks that moved the price up to calculate synthetic delta pressure
        # Wait, the spec says "total ticks in the window". Does total ticks mean *all* ticks,
        # or just the ticks that moved either bid or ask up?
        # "Bullish Imbalance fires when Ask-up ticks are 65% or more of total ticks in the window."
        # It's safest to count all ticks in the window as the denominator, to ensure true dominance.
        self.tick_history.append((now, is_ask_up, is_bid_up))
        
        # Remove ticks older than 60 seconds
        cutoff = now - self.window_seconds
        while self.tick_history and self.tick_history[0][0] < cutoff:
            self.tick_history.popleft()
            
        total_ticks = len(self.tick_history)
        
        if total_ticks < 10:
            # Need a minimum number of ticks to form a statistically significant ratio
            return None
            
        ask_up_count = sum(1 for t in self.tick_history if t[1])
        bid_up_count = sum(1 for t in self.tick_history if t[2])
        
        ask_up_ratio = ask_up_count / total_ticks
        bid_up_ratio = bid_up_count / total_ticks
        
        event = None
        if ask_up_ratio >= self.imbalance_threshold:
            event = {
                "type": "Bullish Imbalance",
                "timestamp": now,
                "ask_up_ratio": round(ask_up_ratio, 2),
                "bid_up_ratio": round(bid_up_ratio, 2),
                "total_ticks": total_ticks
            }
        elif bid_up_ratio >= self.imbalance_threshold:
            event = {
                "type": "Bearish Imbalance",
                "timestamp": now,
                "ask_up_ratio": round(ask_up_ratio, 2),
                "bid_up_ratio": round(bid_up_ratio, 2),
                "total_ticks": total_ticks
            }
            
        return event
