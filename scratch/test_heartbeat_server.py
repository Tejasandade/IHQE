import asyncio
import websockets
import json

async def mock_tiingo(websocket):
    print("Client connected!")
    try:
        # Wait for subscribe message
        msg = await websocket.recv()
        print(f"Received: {msg}")
        
        print("Sending 3 successful messages...")
        for i in range(3):
            await websocket.send(json.dumps({"messageType": "I", "data": "success"}))
            await asyncio.sleep(0.1)
            
        print("Freezing socket for 35 seconds to trigger heartbeat timeout...")
        await asyncio.sleep(35)
        
        print("Sending another message (should be too late)...")
        await websocket.send(json.dumps({"messageType": "I", "data": "late"}))
        
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected.")

async def main():
    print("Starting mock Tiingo WS server on ws://localhost:8765")
    async with websockets.serve(mock_tiingo, "localhost", 8765):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
