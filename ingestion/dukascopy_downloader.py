import os
import subprocess
import time
from datetime import datetime

ASSET = "xauusd"
START_YEAR = 2003
END_YEAR = datetime.now().year
OUTPUT_DIR = "data/historical/xauusd"

os.makedirs(OUTPUT_DIR, exist_ok=True)

success = 0
failed = []

for year in range(START_YEAR, END_YEAR + 1):
    for tf in ["h1", "h4"]:
        outfile = os.path.join(OUTPUT_DIR, f"{ASSET}_{year}_{tf}.csv")
        
        if os.path.exists(outfile):
            with open(outfile, 'r') as f:
                lines = sum(1 for line in f)
            if lines > 1000:
                print(f"[{year} {tf}] Already exists ({lines} rows). Skipping.")
                success += 1
                continue
                
        print(f"[{year} {tf}] Downloading...")
        
        # We use shell=True because npx is a .cmd on Windows
        cmd = [
            "npx", "-y", "dukascopy-node",
            "-i", ASSET,
            "-from", f"{year}-01-01",
            "-to", f"{year}-12-31",
            "-t", tf,
            "-f", "csv",
            "-dir", OUTPUT_DIR,
            "-fn", f"{ASSET}_{year}_{tf}"
        ]
        
        try:
            subprocess.run(" ".join(cmd), shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[{year} {tf}] Done.")
            success += 1
        except subprocess.CalledProcessError:
            print(f"[{year} {tf}] FAILED.")
            failed.append(f"{year}_{tf}")

print("\n============================================")
print(f"  Success: {success} files")
if failed:
    print(f"  Failed files: {failed}")
print("============================================")
