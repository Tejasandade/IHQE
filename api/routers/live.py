"""
IHQE v3 — Live Price WebSocket Router
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Connected WebSocket clients
connected_clients: set[WebSocket] = set()


@router.websocket("/live/price")
async def live_price(websocket: WebSocket):
    """WebSocket endpoint streaming live XAU/USD price from Tiingo.

    Connects to the Tiingo WebSocket and relays price updates
    to the frontend. Falls back to polling ClickHouse ticks
    if Tiingo is unavailable.
    """
    await websocket.accept()
    connected_clients.add(websocket)
    logger.info(f"WebSocket client connected. Total: {len(connected_clients)}")

    try:
        # If Tiingo token is available, relay live data
        if settings.TIINGO_API_TOKEN:
            await _stream_tiingo(websocket)
        else:
            # Fallback: poll latest tick from ClickHouse
            await _poll_clickhouse(websocket)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        connected_clients.discard(websocket)
        logger.info(f"WebSocket client removed. Total: {len(connected_clients)}")


async def _stream_tiingo(websocket: WebSocket):
    """Stream live prices from Tiingo WebSocket."""
    import websockets

    tiingo_url = f"{settings.TIINGO_WS_URL}"

    subscribe_msg = json.dumps({
        "eventName": "subscribe",
        "authorization": settings.TIINGO_API_TOKEN,
        "eventData": {
            "thresholdLevel": settings.TIINGO_THRESHOLD,
            "tickers": [settings.TIINGO_TICKER],
        },
    })

    try:
        async with websockets.connect(tiingo_url) as ws:
            await ws.send(subscribe_msg)

            async for message in ws:
                try:
                    data = json.loads(message)
                    if data.get("messageType") == "A":
                        # Tiingo FX update
                        payload = data.get("data", [])
                        if len(payload) >= 6:
                            price_data = {
                                "type": "price",
                                "ticker": payload[1],
                                "timestamp": payload[2],
                                "midPrice": (float(payload[4]) + float(payload[5])) / 2,
                                "bidPrice": float(payload[4]),
                                "askPrice": float(payload[5]),
                            }
                            await websocket.send_json(price_data)
                except (json.JSONDecodeError, IndexError):
                    continue

    except Exception as e:
        logger.error(f"Tiingo connection error: {e}")
        # Fall back to ClickHouse polling
        await _poll_clickhouse(websocket)


async def _poll_clickhouse(websocket: WebSocket):
    """Poll latest tick from ClickHouse as fallback."""
    from database.clickhouse_client import ClickHouseClient

    db = ClickHouseClient()

    try:
        while True:
            try:
                df = db.query_df(
                    "SELECT ts, (bid + ask) / 2 as mid, bid, ask "
                    "FROM ihqe.xauusd_ticks ORDER BY ts DESC LIMIT 1"
                )
                if not df.empty:
                    row = df.iloc[0]
                    price_data = {
                        "type": "price",
                        "ticker": "xauusd",
                        "timestamp": str(row["ts"]),
                        "midPrice": float(row["mid"]),
                        "bidPrice": float(row["bid"]),
                        "askPrice": float(row["ask"]),
                    }
                    await websocket.send_json(price_data)
            except Exception as e:
                logger.error(f"ClickHouse poll error: {e}")

            await asyncio.sleep(2)  # Poll every 2 seconds
    finally:
        db.close()
