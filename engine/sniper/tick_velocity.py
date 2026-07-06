import time
from collections import deque
from datetime import datetime
from typing import Dict, Any, Optional

class TickVelocityMonitor:
    def __init__(self):
        # We store timestamps of each tick to calculate rates.
        # We only need to keep ticks from the last 30 seconds.
        self.tick_timestamps = deque()
        self.spike_threshold = 3.0  # 300% above 30s average = 4x multiplier, wait - 300% above means 4x or 3x? 
        # "spikes 300% above" -> (5s avg - 30s avg) / 30s avg > 3.0 -> 5s avg > 4.0 * 30s avg.
        # We will use 4.0 as the multiplier (300% above = +300% = 400% of).
        self.multiplier_threshold = 4.0
        self.last_30s_avg = 0.0
        self.last_5s_avg = 0.0
        
    def process_tick(self, timestamp: float = None) -> Optional[Dict[str, Any]]:
        """
        Process a new tick.
        Returns a dictionary with the event if a spike is detected, else None.
        """
        now = timestamp if timestamp is not None else time.time()
        self.tick_timestamps.append(now)
        
        # Remove ticks older than 30 seconds
        cutoff_30s = now - 30.0
        while self.tick_timestamps and self.tick_timestamps[0] < cutoff_30s:
            self.tick_timestamps.popleft()
            
        # Count ticks in the last 5 seconds
        cutoff_5s = now - 5.0
        # Since deque is ordered, we could binary search, but with high frequency ticks
        # we can just count from the right, or we can find the index.
        # Given potential thousands of ticks, let's just do a reverse count or maintain a separate 5s deque.
        # Maintaining a separate 5s deque is more efficient. Wait, we can just iterate from the right.
        count_5s = 0
        for ts in reversed(self.tick_timestamps):
            if ts >= cutoff_5s:
                count_5s += 1
            else:
                break
                
        count_30s = len(self.tick_timestamps)
        
        # Averages (ticks per second)
        self.last_30s_avg = count_30s / 30.0
        self.last_5s_avg = count_5s / 5.0
        
        # Avoid division by zero and require a minimum baseline to avoid noise spikes
        if self.last_30s_avg > 1.0:
            if self.last_5s_avg > (self.last_30s_avg * self.multiplier_threshold):
                return {
                    "type": "Velocity Spike",
                    "timestamp": now,
                    "avg_5s": round(self.last_5s_avg, 2),
                    "avg_30s": round(self.last_30s_avg, 2),
                    "ratio": round(self.last_5s_avg / self.last_30s_avg, 2)
                }
                
        return None
