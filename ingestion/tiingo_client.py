import asyncio
import json
import logging
import time
from datetime import datetime
import websockets

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import settings
from database.clickhouse_client import ClickHouseClient
from engine.sniper.core import sniper_engine

logger = logging.getLogger(__name__)

# Global status for health checks
tiingo_status = {
    "connected": False,
    "last_tick_timestamp": None,
    "reconnect_attempts": 0
}

class TiingoLiveClient:
    def __init__(self):
        self.url = settings.TIINGO_WS_URL
        self.token = settings.TIINGO_API_TOKEN
        self.ticker = settings.TIINGO_TICKER.lower()
        self.db = ClickHouseClient()
        
        self.tick_batch = []
        self.last_flush_time = time.time()
        self.BATCH_SIZE = 500
        self.FLUSH_INTERVAL = 1.0  # seconds

    async def connect_and_listen(self):
        if not self.token:
            logger.warning("TIINGO_API_TOKEN is not set. Tiingo client disabled.")
            return

        reconnect_delay = 1
        max_delay = 60
        consecutive_successes = 0
        reconnect_attempts = 0
        disconnect_time = None

        while True:
            try:
                logger.info(f"Connecting to Tiingo WS: {self.url}")
                async with websockets.connect(self.url) as ws:
                    tiingo_status["connected"] = True
                    # Do NOT reset reconnect_delay yet. We wait for 3 consecutive successes.
                    
                    # Send subscribe payload
                    subscribe = {
                        "eventName": "subscribe",
                        "authorization": self.token,
                        "eventData": {
                            "thresholdLevel": settings.TIINGO_THRESHOLD,
                            "tickers": [self.ticker]
                        }
                    }
                    await ws.send(json.dumps(subscribe))
                    logger.info("Subscribed to Tiingo Forex stream")
                    
                    # Also refresh the cache on startup
                    await sniper_engine.refresh_cache()

                    while True:
                        try:
                            # 30-second heartbeat monitor
                            message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            await self.handle_message(message)
                            
                            consecutive_successes += 1
                            if consecutive_successes == 3:
                                if disconnect_time is not None:
                                    import time
                                    seconds = int(time.time() - disconnect_time)
                                    from alerts.telegram_bot import send_telegram_alert
                                    msg = f"🔌 IHQE — Connection Restored | Reconnected after {seconds}s | Backoff attempts: {reconnect_attempts}"
                                    send_telegram_alert("tiingo_reconnect", msg)
                                    
                                reconnect_delay = 1
                                disconnect_time = None
                                reconnect_attempts = 0
                                tiingo_status["reconnect_attempts"] = 0
                                
                        except asyncio.TimeoutError:
                            logger.error("Tiingo WS Heartbeat Timeout (30s) - no data received. Forcing reconnect.")
                            # Break the inner while loop to force the connection to close and reconnect
                            break
                    
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Tiingo WS connection closed: {e}")
                tiingo_status["connected"] = False
                
            except Exception as e:
                logger.error(f"Tiingo connection error: {e}")
                tiingo_status["connected"] = False
                
            # Reconnection logic
            consecutive_successes = 0
            if disconnect_time is None:
                disconnect_time = time.time()
            reconnect_attempts += 1
            tiingo_status["reconnect_attempts"] = reconnect_attempts
            logger.info(f"Attempting to reconnect in {reconnect_delay} seconds (attempt {reconnect_attempts})...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_delay)

    async def handle_message(self, message: str):
        try:
            data = json.loads(message)
            message_type = data.get("messageType")
            
            if message_type == "A":
                # Quote update
                # Format: ["A", "xauusd", "2026-07-06T15:00:00.000Z", 1000000, 4175.12, 4175.22]
                event_data = data.get("data", [])
                if len(event_data) >= 6:
                    ts_str = event_data[2]
                    bid = float(event_data[4])
                    ask = float(event_data[5])
                    mid = (bid + ask) / 2
                    
                    # 1. Send to Sniper Engine for MTF logic and WebSocket broadcast
                    await sniper_engine.process_tick(mid)
                    
                    # 2. Add to ClickHouse batch
                    # Parse timestamp (Tiingo uses ISO8601 with Z)
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    tiingo_status["last_tick_timestamp"] = ts.isoformat() + "Z"
                    
                    self.tick_batch.append({
                        "ts": ts,
                        "bid": bid,
                        "ask": ask
                    })
                    
                    current_time = time.time()
                    if len(self.tick_batch) >= self.BATCH_SIZE or (current_time - self.last_flush_time) >= self.FLUSH_INTERVAL:
                        self.flush_batch()
                        self.last_flush_time = current_time

            elif message_type == "I":
                logger.info(f"Tiingo Info: {data}")
            elif message_type == "E":
                logger.error(f"Tiingo Error: {data}")
                
        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.error(f"Error handling Tiingo message: {e}")

    def flush_batch(self):
        if not self.tick_batch:
            return
        
        batch = self.tick_batch.copy()
        self.tick_batch.clear()
        
        try:
            self.db.insert_ticks(batch)
            # logger.debug(f"Flushed {len(batch)} ticks to ClickHouse")
        except Exception as e:
            logger.error(f"Failed to insert ticks to ClickHouse: {e}")

async def start_tiingo_client():
    client = TiingoLiveClient()
    await client.connect_and_listen()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_tiingo_client())
