from database.clickhouse_client import ClickHouseClient
db = ClickHouseClient()
df = db.query_df("SELECT count() as c FROM ihqe.bos_events WHERE timeframe = '4H'")
print(f'Total 4H BOS Events: {df.iloc[0][0]}')
