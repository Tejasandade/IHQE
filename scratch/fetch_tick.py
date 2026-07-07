import asyncio
import json
import websockets
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import settings

async def fetch_tick():
    url = settings.TIINGO_WS_URL
    token = settings.TIINGO_API_TOKEN
    ticker = settings.TIINGO_TICKER.lower()
    
    print(f"Connecting to {url} with token {token[:5]}...")
    
    async with websockets.connect(url) as ws:
        subscribe = {
            "eventName": "subscribe",
            "authorization": token,
            "eventData": {
                "thresholdLevel": 5,
                "tickers": [ticker]
            }
        }
        await ws.send(json.dumps(subscribe))
        
        # Wait for the first 'A' message
        async for message in ws:
            data = json.loads(message)
            if data.get("messageType") == "A":
                print("RAW TICK JSON:")
                print(message)
                break

if __name__ == "__main__":
    asyncio.run(fetch_tick())
