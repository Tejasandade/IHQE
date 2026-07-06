import asyncio
import time
from typing import Dict, Any, List

from .tick_velocity import TickVelocityMonitor
from .imbalance import QuoteImbalanceDetector
from .absorption import AbsorptionMonitor

class SniperEngine:
    """
    Core Sniper Engine orchestrating real-time order flow anomalies.
    """
    def __init__(self):
        self.tick_velocity = TickVelocityMonitor()
        self.imbalance = QuoteImbalanceDetector()
        self.absorption = AbsorptionMonitor()
        
        # SSE broadcasting
        self.subscribers: List[asyncio.Queue] = []
        
    async def process_tick(self, bid: float, ask: float, timestamp: float = None):
        """
        Process a raw incoming tick from Tiingo.
        """
        now = timestamp if timestamp is not None else time.time()
        mid_price = (bid + ask) / 2.0
        
        events = []
        
        # 1. Tick Velocity
        velocity_event = self.tick_velocity.process_tick(now)
        if velocity_event:
            events.append(velocity_event)
            
        # 2. Imbalance
        imbalance_event = self.imbalance.process_tick(bid, ask, now)
        if imbalance_event:
            events.append(imbalance_event)
            
        # 3. Absorption
        # tick velocity is "elevated" if 5s avg > 30s avg
        # (even if not spiked 300%)
        is_elevated = False
        if self.tick_velocity.last_30s_avg > 0 and self.tick_velocity.last_5s_avg > self.tick_velocity.last_30s_avg:
            is_elevated = True
            
        absorption_event = self.absorption.process_tick(mid_price, is_elevated, now)
        if absorption_event:
            events.append(absorption_event)
            
        # Broadcast detected anomalies to all connected SSE clients
        for event in events:
            await self._broadcast(event)
            
    async def _broadcast(self, data: Dict[str, Any]):
        """Push an event to all subscriber queues."""
        for q in self.subscribers:
            await q.put(data)
            
    async def subscribe(self) -> asyncio.Queue:
        """Subscribe to the SSE event stream."""
        q = asyncio.Queue()
        self.subscribers.append(q)
        return q
        
    def unsubscribe(self, q: asyncio.Queue):
        """Unsubscribe from the SSE event stream."""
        if q in self.subscribers:
            self.subscribers.remove(q)

# Global instance for the FastAPI app to use
sniper_engine = SniperEngine()
