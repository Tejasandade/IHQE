import time
from collections import deque
from typing import Dict, Any, Optional

class AbsorptionMonitor:
    def __init__(self):
        # We need to track price over a 60-second window
        # Store tuples of (timestamp, price)
        self.price_history = deque()
        self.window_seconds = 60.0
        self.range_threshold = 1.50  # Fixed $1.50 dollar amount range

    def process_tick(self, mid_price: float, tick_velocity_elevated: bool, timestamp: float = None) -> Optional[Dict[str, Any]]:
        """
        Process a new price tick.
        `tick_velocity_elevated` should be True if the current 5s tick average > 30s average.
        Returns a dictionary with the event if absorption is detected, else None.
        """
        now = timestamp if timestamp is not None else time.time()
        
        self.price_history.append((now, mid_price))
        
        # Remove ticks older than 60 seconds
        cutoff = now - self.window_seconds
        while self.price_history and self.price_history[0][0] < cutoff:
            self.price_history.popleft()
            
        # We can only evaluate if we have at least 60 seconds of data.
        # Check if the oldest tick is close to 60 seconds old.
        if len(self.price_history) < 2:
            return None
            
        oldest_time = self.price_history[0][0]
        if (now - oldest_time) < (self.window_seconds - 1.0):
            # Not enough time has elapsed to form a true 60s consolidation
            return None
            
        if not tick_velocity_elevated:
            return None
            
        # Check the price range in this 60s window
        prices = [p[1] for p in self.price_history]
        max_price = max(prices)
        min_price = min(prices)
        price_range = max_price - min_price
        
        if price_range <= self.range_threshold:
            return {
                "type": "Possible Absorption",
                "timestamp": now,
                "range": round(price_range, 3),
                "duration": round(now - oldest_time, 1),
                "mid_price": mid_price
            }
            
        return None
