from database.clickhouse_client import ClickHouseClient
db = ClickHouseClient()
df = db.query_df("SELECT count() as c FROM ihqe.xauusd_ohlcv WHERE timeframe = '1H'")
print(f'Total 1H Rows: {df.iloc[0][0]}')

with open('engine/fvg_detector.py', 'r') as f:
    lines = f.readlines()

in_func = False
print('\n--- _is_fvg_in_zone CODE ---')
for line in lines:
    if 'def _is_fvg_in_zone' in line:
        in_func = True
    if in_func:
        print(line, end='')
        if 'return False' in line:
            break
