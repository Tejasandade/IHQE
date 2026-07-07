"""
IHQE v3 — Live Price WebSocket Router
"""

import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from config import settings
from engine.sniper.core import sniper_engine

router = APIRouter()
logger = logging.getLogger(__name__)

@router.websocket("/live/price")
async def live_price(websocket: WebSocket):
    """WebSocket endpoint streaming live XAU/USD price.
    Registers the connection with the centralized SniperEngine.
    """
    await sniper_engine.register(websocket)
    logger.info(f"WebSocket client connected. Total: {len(sniper_engine.websockets)}")

    try:
        # Keep connection open and wait for messages from client (if any)
        # The broadcasting is handled by SniperEngine
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        sniper_engine.disconnect(websocket)
        logger.info(f"WebSocket client removed. Total: {len(sniper_engine.websockets)}")
@router.post("/internal/refresh-cache")
async def trigger_cache_refresh():
    """Trigger a refresh of the SniperEngine 0.5 level cache."""
    await sniper_engine.refresh_cache()
    return {"status": "ok", "message": "Cache refreshed"}
