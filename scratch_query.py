import logging
logging.basicConfig(level=logging.INFO)

from database.clickhouse_client import ClickHouseClient
from engine.bos_detector import BOSDetector
from engine.fibonacci import FibonacciCalculator
from engine.fvg_detector import FVGDetector
import pandas as pd

db = ClickHouseClient()

print("Fetching 2024 OHLCV data...")
candles = db.get_ohlcv("4H", start="2024-01-01", end="2024-12-31")
print(f"Total 4H candles in 2024: {len(candles)}")

bos_d = BOSDetector()
fib_d = FibonacciCalculator()
fvg_d = FVGDetector()

print("\n--- Step 1: Detect BOS ---")
all_bos = bos_d.detect(candles, "4H")
print(f"BOS Count: {len(all_bos)}")

print("\n--- Step 2: Detect Fib Grids ---")
all_grids = []
for bos in all_bos:
    grid = fib_d.build_grid_from_bos(bos, "4H")
    if grid:
        all_grids.append(grid)
print(f"Fib Grids Count: {len(all_grids)}")

print("\n--- Step 3: Detect FVGs in Zones ---")
all_fvgs = 0
for i, bos in enumerate(all_bos):
    start_ts = bos['bos_candle_ts']
    if i < len(all_bos) - 1:
        end_ts = all_bos[i+1]['bos_candle_ts']
        chunk = candles[(candles.index >= start_ts) & (candles.index <= end_ts)]
    else:
        chunk = candles[candles.index >= start_ts]
        
    grid = fib_d.build_grid_from_bos(bos, "4H")
    if not grid:
        continue
        
    zone_upper = grid['level_0_500']
    zone_lower = grid['level_0_000'] if grid['direction'] == 'bullish' else grid['level_1_000']
    
    fvgs = fvg_d.detect_in_zone(
        chunk, 
        "4H", 
        zone_upper, 
        zone_lower,
        grid['direction']
    )
    all_fvgs += len(fvgs)
    
print(f"FVG Count: {all_fvgs}")
