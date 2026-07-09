import asyncio
import websockets
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('mock_client')

async def connect_and_listen():
    reconnect_delay = 1
    max_delay = 60
    consecutive_successes = 0

    while True:
        try:
            logger.info('Connecting...')
            async with websockets.connect('ws://localhost:8765') as ws:
                await ws.send('subscribe')
                while True:
                    try:
                        # 3 second timeout for quick testing
                        msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        logger.info(f'Received: {msg}')
                        consecutive_successes += 1
                        if consecutive_successes >= 3:
                            reconnect_delay = 1
                    except asyncio.TimeoutError:
                        logger.error('Heartbeat Timeout! Forcing reconnect.')
                        break
        except Exception as e:
            logger.error(f'Error: {e}')
        
        consecutive_successes = 0
        logger.info(f'Reconnecting in {reconnect_delay} seconds...')
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, max_delay)

asyncio.run(connect_and_listen())
