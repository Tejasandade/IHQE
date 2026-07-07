import asyncio
import sys
import os
import logging

logging.basicConfig(level=logging.INFO)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from engine.sniper.core import sniper_engine

async def run_test():
    # Mock cache
    sniper_engine.active_05_levels = {'12M': 4150.0}
    
    # Send a tick below 0.5 level
    print("Sending price 4149.0")
    await sniper_engine.process_tick(4149.0)
    
    # Send a tick above 0.5 level to trigger cross
    print("Sending price 4151.0 (Crossing 0.5 level!)")
    await sniper_engine.process_tick(4151.0)
    
    # Give time for async task to run
    await asyncio.sleep(2)
    print("Done")

if __name__ == "__main__":
    asyncio.run(run_test())

logging.getLogger().setLevel(logging.INFO)
