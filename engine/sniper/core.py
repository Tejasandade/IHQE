import asyncio
import logging
from typing import Dict, List, Any
from fastapi import WebSocket
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from database.clickhouse_client import ClickHouseClient
from engine.intelligence.mtf_engine import run_intelligence_engine
from config import settings

logger = logging.getLogger(__name__)

class SniperEngine:
    def __init__(self):
        self.active_05_levels: Dict[str, float] = {}
        self.last_broadcast_price: float = 0.0
        self.websockets: List[WebSocket] = []
        self._cache_lock = asyncio.Lock()
        
    async def refresh_cache(self):
        """Fetch active 0.5 levels from ClickHouse for all 5 timeframes."""
        db = ClickHouseClient()
        new_levels = {}
        try:
            for tf in settings.TIMEFRAME_CASCADE:
                if tf == 'W':
                    continue # Not part of intelligence engine
                
                df = db.get_fib_grids(tf, active_only=True)
                if not df.empty:
                    latest = df.iloc[-1]
                    level = float(latest.get("level_0_500", latest.get("level_0_5", 0.0)))
                    if level > 0:
                        new_levels[tf] = level
        except Exception as e:
            logger.error(f"Failed to refresh 0.5 cache: {e}")
        finally:
            db.close()
            
        async with self._cache_lock:
            self.active_05_levels = new_levels
        logger.info(f"SniperEngine cache refreshed: {self.active_05_levels}")

    async def process_tick(self, mid_price: float):
        """Process a live tick, check for crosses, and broadcast."""
        
        async with self._cache_lock:
            levels = self.active_05_levels.copy()
            
        if hasattr(self, 'last_mid_price') and self.last_mid_price > 0:
            crossed = False
            for tf, level in levels.items():
                if (self.last_mid_price < level and mid_price >= level) or \
                   (self.last_mid_price > level and mid_price <= level):
                    print(f"Price crossed 0.5 level ({level}) for timeframe {tf}. Triggering Intelligence Engine.")
                    logger.info(f"Price crossed 0.5 level ({level}) for timeframe {tf}. Triggering Intelligence Engine.")
                    crossed = True
                    break
            
            if crossed:
                asyncio.create_task(self._run_mtf())
                
        self.last_mid_price = mid_price

        # WebSocket Push (delta > $0.10)
        if abs(mid_price - self.last_broadcast_price) >= 0.10:
            self.last_broadcast_price = mid_price
            await self.broadcast({
                "type": "price",
                "midPrice": mid_price,
                "bidPrice": mid_price,
                "askPrice": mid_price,
                "timestamp": None
            })

    async def _run_mtf(self):
        try:
            await asyncio.to_thread(run_intelligence_engine)
            # We can also broadcast the updated intelligence score here
        except Exception as e:
            logger.error(f"MTF Engine trigger failed: {e}")

    async def register(self, websocket: WebSocket):
        await websocket.accept()
        self.websockets.append(websocket)
        if hasattr(self, 'last_mid_price'):
            await websocket.send_json({
                "type": "price",
                "midPrice": self.last_mid_price,
                "bidPrice": self.last_mid_price,
                "askPrice": self.last_mid_price,
                "timestamp": None
            })
            
    def disconnect(self, websocket: WebSocket):
        if websocket in self.websockets:
            self.websockets.remove(websocket)

    async def broadcast(self, message: dict):
        for ws in self.websockets.copy():
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)

sniper_engine = SniperEngine()
