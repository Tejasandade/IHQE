# IHQE — Institutional Hybrid Quant Engine
## Master Project Prompt for Coding Agents

---

## 0. HOW TO USE THIS DOCUMENT

This is the single source of truth for the IHQE project. Read it fully before writing any code. Every architectural decision, naming convention, algorithm rule, and database schema is defined here. When in doubt, refer back to this document. Do not invent conventions not listed here.

The companion document `IHQE_v2_1_Project_Specification.docx` contains the full business and strategy specification. This prompt contains everything a coding agent needs to implement it.

---

## 1. PROJECT MISSION

Build a fully automated algorithmic trading platform for **Spot Gold CFDs (XAU/USD)** that:

1. Downloads 20+ years of historical price data and maps every valid structural setup from 2003 to the current live bar automatically
2. Detects **Fair Value Gaps (FVGs)** and draws **Fibonacci grids** across 6 cascading timeframes using strict algorithmic rules — no human drawing required
3. Identifies **Double Trade setups** (Draw on Liquidity) where a counter-trend trade rides price to the macro target, then flips to the primary direction
4. Generates **advance trade signals** days, weeks, or months before the execution window opens
5. Executes entries using a **real-time quote-tick sniper** that detects institutional absorption at the precise reversal millisecond
6. Displays everything on an **Ultimate Trading Dashboard** (Streamlit + Plotly) accessible from any browser

This is built in 4 phases. **Start with Phase 1 only.** Do not build Phase 2+ code until Phase 1 is complete and tested.

---

## 2. COMPLETE TECHNOLOGY STACK

| Layer | Tool | Version / Notes |
|---|---|---|
| Language | Python | 3.11+ |
| Historical Data | dukascopy-node | CLI via Node.js 18+, no account needed |
| Live Data | Tiingo WebSocket API | Free tier, requires API token |
| Database | ClickHouse | 23.x, run via Docker |
| Container | Docker + Docker Compose | Latest stable |
| Data Processing | Pandas | 2.x |
| Numerical | NumPy | 1.26+ |
| Dashboard | Streamlit | 1.35+ |
| Charts | Plotly | 5.x |
| WebSocket client | websocket-client | 1.7+ |
| HTTP client | requests | 2.31+ |
| Process manager | tmux | System package |
| Server OS | Ubuntu 22.04 LTS | Headless VPS |
| Node.js | 18 LTS | For dukascopy-node only |

**Install order:** Docker → ClickHouse container → Node.js → Python dependencies → dukascopy-node

---

## 3. PROJECT DIRECTORY STRUCTURE

Create this exact structure. Do not deviate from it.

```
ihqe/
│
├── config/
│   ├── settings.py          # All config constants — API keys, DB connection, asset settings
│   └── .env                 # Environment variables (never commit this file)
│
├── data/
│   ├── historical/          # Raw downloaded Dukascopy CSV files live here
│   │   └── xauusd/          # Organised by year: xauusd_2003.csv, xauusd_2004.csv, etc.
│   └── processed/           # Cleaned and rolled-up OHLCV parquet files (intermediate cache)
│
├── database/
│   ├── docker-compose.yml   # ClickHouse container definition
│   ├── init_schema.sql      # All CREATE TABLE statements (run once on first setup)
│   └── clickhouse_client.py # Python ClickHouse connection wrapper class
│
├── ingestion/
│   ├── dukascopy_downloader.sh   # Shell script wrapping dukascopy-node CLI commands
│   ├── dukascopy_loader.py       # Reads downloaded CSVs and inserts into ClickHouse
│   └── tiingo_stream.py          # Tiingo WebSocket live tick streamer class
│
├── engine/
│   ├── ohlcv_builder.py     # Rolls up raw tick/1H data into all higher timeframes
│   ├── fvg_detector.py      # Core FVG detection algorithm (both bullish and bearish)
│   ├── fibonacci.py         # Fibonacci grid calculator and swing anchor finder
│   ├── cascade.py           # Six-timeframe cascade state machine
│   ├── double_trade.py      # Counter-trend grid detection and double trade pairing
│   └── signal_engine.py     # Signal classification (Macro/Mid/Active/Flip/Execute)
│
├── sniper/
│   ├── tick_velocity.py     # Rolling tick frequency calculator
│   ├── quote_imbalance.py   # Synthetic bid/ask delta calculator
│   ├── absorption.py        # Iceberg absorption detector
│   └── sniper_engine.py     # Combines all three metrics, fires entry signal
│
├── dashboard/
│   ├── app.py               # Main Streamlit entry point
│   ├── panel_state_map.py   # Panel 1: Historical State Map charts
│   ├── panel_cascade.py     # Panel 2: Cascade Gate Status Board
│   ├── panel_signals.py     # Panel 3: Advance Signal Board
│   └── panel_sniper.py      # Panel 4: Live Sniper Console
│
├── tests/
│   ├── test_fvg_detector.py
│   ├── test_fibonacci.py
│   ├── test_cascade.py
│   └── test_double_trade.py
│
├── run_phase1.sh            # Phase 1 startup script
├── requirements.txt
└── README.md
```

---

## 4. ENVIRONMENT CONFIGURATION

### `config/settings.py`
```python
import os
from dotenv import load_dotenv

load_dotenv()

# ── Tiingo API ──────────────────────────────────────────────────────────────
TIINGO_API_TOKEN = os.getenv("TIINGO_API_TOKEN")
TIINGO_WS_URL    = "wss://api.tiingo.com/fx"
TIINGO_TICKER    = "xauusd"
TIINGO_THRESHOLD = 5  # Filter level — suppresses micro-pip noise

# ── ClickHouse ──────────────────────────────────────────────────────────────
CH_HOST     = os.getenv("CH_HOST", "localhost")
CH_PORT     = int(os.getenv("CH_PORT", 9000))
CH_DATABASE = "ihqe"
CH_USER     = os.getenv("CH_USER", "default")
CH_PASSWORD = os.getenv("CH_PASSWORD", "")

# ── Asset ────────────────────────────────────────────────────────────────────
ASSET          = "XAUUSD"
HISTORY_START  = "2003-01-01"
HISTORY_END    = "today"  # Resolved at runtime

# ── Timeframe definitions ─────────────────────────────────────────────────────
# Keys are used as canonical identifiers throughout the entire codebase
TIMEFRAMES = {
    "12M":  {"label": "12-Month",  "dukascopy_interval": "MN1",  "resample_rule": "12ME"},
    "3M":   {"label": "3-Month",   "dukascopy_interval": "MN1",  "resample_rule": "3ME"},
    "1M":   {"label": "1-Month",   "dukascopy_interval": "MN1",  "resample_rule": "ME"},
    "W":    {"label": "Weekly",    "dukascopy_interval": "W1",   "resample_rule": "W-MON"},
    "4H":   {"label": "4-Hour",    "dukascopy_interval": "H4",   "resample_rule": "4h"},
    "1H":   {"label": "1-Hour",    "dukascopy_interval": "H1",   "resample_rule": "1h"},
}
TIMEFRAME_CASCADE = ["12M", "3M", "1M", "W", "4H", "1H"]  # Ordered top to bottom

# ── Fibonacci levels ──────────────────────────────────────────────────────────
FIB_LEVELS = {
    "1.0":   1.000,
    "0.786": 0.786,
    "0.618": 0.618,
    "0.5":   0.500,
    "0.382": 0.382,
    "0.236": 0.236,
    "0.0":   0.000,
}
DISCOUNT_ZONE_UPPER = 0.500   # Below this = discount zone (Long setups)
SNIPER_ZONE_LONG    = 0.618   # Deep sniper entry for long
PREMIUM_ZONE_LOWER  = 0.500   # Above this = premium zone (Short setups)
SNIPER_ZONE_SHORT   = 0.382   # Deep sniper entry for short

# ── Counter-trend (Double Trade) settings ────────────────────────────────────
CT_MIN_MACRO_GATES = 3  # Minimum primary cascade gates confirmed before CT watch begins
```

### `config/.env` (template — user fills in)
```
TIINGO_API_TOKEN=your_token_here
CH_HOST=localhost
CH_PORT=9000
CH_USER=default
CH_PASSWORD=
```

---

## 5. DATABASE SCHEMA

### `database/docker-compose.yml`
```yaml
version: '3.8'
services:
  clickhouse:
    image: clickhouse/clickhouse-server:23.8
    container_name: ihqe_clickhouse
    ports:
      - "9000:9000"
      - "8123:8123"
    volumes:
      - clickhouse_data:/var/lib/clickhouse
      - ./init_schema.sql:/docker-entrypoint-initdb.d/init_schema.sql
    ulimits:
      nofile:
        soft: 262144
        hard: 262144
    restart: unless-stopped

volumes:
  clickhouse_data:
```

### `database/init_schema.sql`
```sql
CREATE DATABASE IF NOT EXISTS ihqe;

-- ── Raw tick quotes from Tiingo live stream ──────────────────────────────────
CREATE TABLE IF NOT EXISTS ihqe.xauusd_ticks
(
    ts          DateTime64(3, 'UTC'),   -- millisecond precision
    bid         Float64,
    ask         Float64,
    mid         Float64 MATERIALIZED (bid + ask) / 2,
    spread      Float64 MATERIALIZED ask - bid,
    source      String DEFAULT 'tiingo'
)
ENGINE = MergeTree()
ORDER BY ts
PARTITION BY toYYYYMM(ts);

-- ── OHLCV candles for all timeframes ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ihqe.xauusd_ohlcv
(
    timeframe   String,    -- '12M' | '3M' | '1M' | 'W' | '4H' | '1H'
    ts          DateTime64(3, 'UTC'),
    open        Float64,
    high        Float64,
    low         Float64,
    close       Float64,
    volume      Float64 DEFAULT 0,
    tick_count  UInt32  DEFAULT 0    -- number of ticks in this candle
)
ENGINE = ReplacingMergeTree()
ORDER BY (timeframe, ts)
PARTITION BY (timeframe, toYear(ts));

-- ── Detected Fair Value Gaps ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ihqe.fvg_events
(
    fvg_id          String,         -- UUID
    timeframe       String,
    direction       String,         -- 'bullish' | 'bearish'
    ts_candle1      DateTime64(3, 'UTC'),
    ts_candle3      DateTime64(3, 'UTC'),
    gap_top         Float64,        -- top boundary of the gap
    gap_bottom      Float64,        -- bottom boundary of the gap
    gap_size        Float64,        -- gap_top - gap_bottom
    gap_size_pct    Float64,        -- gap as % of price
    is_extreme      UInt8 DEFAULT 0, -- 1 = first FVG in this zone (priority FVG)
    is_mitigated    UInt8 DEFAULT 0, -- 1 = price has returned into this gap
    ts_mitigated    Nullable(DateTime64(3, 'UTC')),
    parent_fvg_id   Nullable(String) -- links to parent timeframe's FVG
)
ENGINE = ReplacingMergeTree(ts_candle3)
ORDER BY (timeframe, ts_candle1);

-- ── Fibonacci grids ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ihqe.fib_grids
(
    grid_id         String,         -- UUID
    timeframe       String,
    direction       String,         -- 'bullish' | 'bearish'
    anchor_fvg_id   String,         -- the FVG that triggered this grid
    swing_low_ts    DateTime64(3, 'UTC'),
    swing_high_ts   DateTime64(3, 'UTC'),
    swing_low       Float64,
    swing_high      Float64,
    total_range     Float64,
    -- Pre-calculated key levels
    level_1_000     Float64,        -- swing high (bullish) or swing low (bearish)
    level_0_786     Float64,
    level_0_618     Float64,        -- sniper zone deep (long)
    level_0_500     Float64,        -- equilibrium / zone boundary
    level_0_382     Float64,        -- sniper zone deep (short)
    level_0_236     Float64,
    level_0_000     Float64,        -- swing low (bullish) or swing high (bearish)
    is_active       UInt8 DEFAULT 1, -- 0 = grid invalidated (price closed beyond swing)
    parent_grid_id  Nullable(String) -- links to the parent timeframe's grid
)
ENGINE = ReplacingMergeTree()
ORDER BY (timeframe, swing_low_ts);

-- ── Cascade gate states ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ihqe.cascade_states
(
    state_id        String,         -- UUID
    cascade_type    String,         -- 'primary' | 'counter_trend'
    direction       String,         -- 'bullish' | 'bearish'
    timeframe       String,
    gate_status     String,         -- 'waiting' | 'fvg_confirmed' | 'zone_approach' | 'sniper_active'
    confirmed_at    Nullable(DateTime64(3, 'UTC')),
    fvg_id          Nullable(String),
    grid_id         Nullable(String),
    ts_updated      DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(ts_updated)
ORDER BY (cascade_type, direction, timeframe);

-- ── Trade signals ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ihqe.trade_signals
(
    signal_id       String,         -- UUID
    signal_type     String,         -- 'macro_alert' | 'mid_alert' | 'active' | 'flip' | 'execute'
    trade_type      String,         -- 'primary' | 'counter_trend'
    direction       String,         -- 'long' | 'short'
    gates_confirmed UInt8,          -- how many of 6 cascade gates are open
    target_upper    Float64,        -- upper boundary of sniper zone
    target_lower    Float64,        -- lower boundary of sniper zone
    linked_signal_id Nullable(String), -- for double trade pairs, links CT and primary
    published_at    DateTime64(3, 'UTC'),
    status          String DEFAULT 'open'  -- 'open' | 'executed' | 'invalidated'
)
ENGINE = ReplacingMergeTree(published_at)
ORDER BY (signal_type, published_at);

-- ── Historical signal outcomes (backtest results) ──────────────────────────────
CREATE TABLE IF NOT EXISTS ihqe.signal_outcomes
(
    signal_id       String,
    entry_price     Float64,
    exit_price      Float64,
    peak_price      Float64,        -- best price reached in trade direction
    move_size       Float64,        -- peak_price - entry_price (signed)
    move_size_pct   Float64,
    result          String,         -- 'win' | 'loss' | 'breakeven'
    closed_at       DateTime64(3, 'UTC')
)
ENGINE = MergeTree()
ORDER BY closed_at;
```

---

## 6. CORE ALGORITHM RULES

These rules are absolute. The code must implement them exactly. No interpretation.

### 6.1 FVG Detection Rules
```
BULLISH FVG:
  - Requires exactly 3 consecutive candles
  - Condition: candle[2].low > candle[0].high
  - Gap top    = candle[2].low
  - Gap bottom = candle[0].high
  - Gap size   = gap_top - gap_bottom (must be > 0, any positive value qualifies)
  - Wick rule  : candle[1] lows must NOT sweep below candle[0].low
  - is_extreme : True if this is the FIRST bullish FVG detected in the current discount zone
    on this timeframe. Subsequent FVGs in the same zone are recorded but not flagged extreme.

BEARISH FVG:
  - Condition: candle[2].high < candle[0].low
  - Gap top    = candle[0].low
  - Gap bottom = candle[2].high
  - Wick rule  : candle[1] highs must NOT sweep above candle[0].high
  - is_extreme : True if first bearish FVG in the current premium zone on this timeframe

DETECTION TIMING:
  - Intrabar — the FVG is flagged as soon as the condition is mathematically satisfied
    on the available data. No waiting for candle close.

MITIGATION:
  - A bullish FVG is mitigated when price trades back down into the gap (close <= gap_bottom)
  - A bearish FVG is mitigated when price trades back up into the gap (close >= gap_top)
  - Mitigated FVGs are kept in the database with is_mitigated = 1, never deleted
```

### 6.2 Fibonacci Anchor Rules
```
BULLISH GRID:
  - Point A (swing_low)  = The candle low at the exact point where price broke structure
    (BOS) upward after exiting a discount zone. Specifically: the lowest low in the
    lookback window immediately before the displacement candle that created the FVG.
  - Point B (swing_high) = The highest high reached after the BOS, before the next
    structural pullback begins (first candle that closes below the prior candle's low).

BEARISH GRID:
  - Point A (swing_high) = Highest high before the bearish displacement that created the FVG
  - Point B (swing_low)  = Lowest low reached after the bearish BOS

LEVEL CALCULATION (bullish example):
  range         = swing_high - swing_low
  level_1_000   = swing_high
  level_0_786   = swing_high - (range * 0.786)
  level_0_618   = swing_high - (range * 0.618)   ← Long Sniper Zone deep end
  level_0_500   = swing_high - (range * 0.500)   ← Zone boundary (equilibrium)
  level_0_382   = swing_high - (range * 0.382)
  level_0_236   = swing_high - (range * 0.236)
  level_0_000   = swing_low

GRID INVALIDATION:
  - Bullish grid: invalidated if price closes below swing_low (level_0_000)
  - Bearish grid: invalidated if price closes above swing_high (level_0_000 equivalent)
  - Set is_active = 0 in database. Never delete invalidated grids.
```

### 6.3 Six-Timeframe Cascade Logic
```
CASCADE ORDER: 12M → 3M → 1M → W → 4H → 1H

For each timeframe gate, the state machine follows:

STATE: 'waiting'
  Entry condition: This is the default state
  Transition to 'fvg_confirmed' when:
    - The timeframe above this one has gate_status = 'fvg_confirmed' (or this is 12M)
    - An extreme FVG has formed inside the parent timeframe's discount/premium zone
    - The Fibonacci grid for this timeframe has been calculated and stored

STATE: 'fvg_confirmed'
  A Fibonacci grid is now active on this timeframe
  Transition to 'zone_approach' when:
    - Live price comes within 2% of the 0.5 level on this timeframe's grid

STATE: 'zone_approach'
  Transition to 'sniper_active' when:
    - Live price ticks into the discount zone (below 0.5 for Long, above 0.5 for Short)
    - Intrabar — no close required

STATE: 'sniper_active'
  Only possible on the 1H timeframe (the terminal execution gate)
  Triggers the Sniper Engine

GATE COUNT:
  gates_confirmed = count of timeframes with status IN ('fvg_confirmed', 'zone_approach', 'sniper_active')
```

### 6.4 Counter-Trend (Double Trade) Logic
```
ACTIVATION:
  A counter-trend cascade watch begins when:
    - Primary cascade gates_confirmed >= CT_MIN_MACRO_GATES (default 3)
    - Price is moving TOWARD the primary macro target (retracing)

COUNTER-TREND DIRECTION:
  - Primary = bearish → Counter-trend = bullish
  - Primary = bullish → Counter-trend = bearish

COUNTER-TREND CASCADE:
  - Runs the identical six-timeframe cascade but in the opposite direction
  - cascade_type = 'counter_trend' in database

EXIT TARGET:
  - The counter-trend trade exits when price reaches level_0_500 of the primary macro grid
  - At that exact level: emit a 'flip' signal
    → Close counter-trend trade
    → Open primary macro trade

GRID VALIDITY CONDITION:
  - CT grid is only valid if the top (bullish CT) or bottom (bearish CT) of the CT grid
    is within 3% of the primary macro 0.5 level. If not within 3%, the CT grid is logged
    but NOT presented as a tradeable double trade setup.
```

### 6.5 Signal Classification Logic
```python
def classify_signal(gates_confirmed: int, ct_gates_confirmed: int, 
                    price_in_sniper_zone: bool) -> str:
    if price_in_sniper_zone and gates_confirmed == 6:
        return "execute"
    elif gates_confirmed == 6:
        return "active"
    elif gates_confirmed >= 4:
        return "mid_alert"
    elif gates_confirmed >= 2:
        return "macro_alert"
    else:
        return None  # Not a publishable signal yet
```

---

## 7. PHASE 1 — EXACT IMPLEMENTATION TASKS

Build Phase 1 tasks in this exact order. Do not jump ahead.

### Task 1.1 — Docker + ClickHouse Setup
```bash
# Files to create:
#   database/docker-compose.yml   (schema above)
#   database/init_schema.sql      (schema above)

# Commands that must work after implementation:
docker-compose -f database/docker-compose.yml up -d
docker exec ihqe_clickhouse clickhouse-client --query "SHOW DATABASES"
# Expected output includes: ihqe
```

### Task 1.2 — ClickHouse Python Client Wrapper
File: `database/clickhouse_client.py`

Requirements:
- Use the `clickhouse-driver` Python package
- Class: `ClickHouseClient`
- Methods required:
  - `insert_ticks(rows: list[dict])` — bulk insert into `ihqe.xauusd_ticks`
  - `insert_ohlcv(timeframe: str, rows: list[dict])` — bulk insert into `ihqe.xauusd_ohlcv`
  - `query_df(sql: str) -> pd.DataFrame` — returns a Pandas DataFrame
  - `get_latest_tick_ts() -> datetime | None` — returns most recent tick timestamp
  - `get_ohlcv(timeframe: str, start: str, end: str) -> pd.DataFrame`
- All methods must handle connection errors with retry logic (3 retries, 2 second backoff)
- Connection must be lazy (only connect on first use, not at import time)

### Task 1.3 — Dukascopy Historical Downloader
File: `ingestion/dukascopy_downloader.sh`

Requirements:
- Downloads XAU/USD tick data year by year from 2003 to current year
- Each year saved as: `data/historical/xauusd/xauusd_YYYY.csv`
- Uses `npx dukascopy-node` — no global install required
- Skips years already downloaded (check if file exists and has >1000 lines)
- Prints progress: `[2003] Downloading... Done. (X rows)`
- On failure: retries once, then skips and continues to next year

```bash
#!/bin/bash
# Usage: bash ingestion/dukascopy_downloader.sh
# Downloads one year at a time to avoid memory issues
ASSET="xauusd"
START_YEAR=2003
END_YEAR=$(date +%Y)
OUTPUT_DIR="data/historical/xauusd"
mkdir -p "$OUTPUT_DIR"
# ... implementation
```

### Task 1.4 — Dukascopy CSV Loader
File: `ingestion/dukascopy_loader.py`

Requirements:
- Reads all CSV files from `data/historical/xauusd/`
- Dukascopy tick CSV format: `timestamp,askOpen,askHigh,askLow,askClose,bidOpen,bidHigh,bidLow,bidClose,volume`
- Calculates `mid = (ask + bid) / 2` and `spread = ask - bid`
- Inserts into `ihqe.xauusd_ticks` in batches of 100,000 rows
- Skips rows already in database (check by timestamp range)
- After inserting ticks: calls `ohlcv_builder.py` to roll up all timeframes
- Must show a progress bar (use `tqdm`)
- Log output: `[INFO] Loaded 2003: 1,247,832 ticks inserted. Skipped: 0 duplicates.`

### Task 1.5 — OHLCV Builder
File: `engine/ohlcv_builder.py`

Requirements:
- Reads raw ticks from `ihqe.xauusd_ticks`
- Uses Pandas resample to build OHLCV for all 6 timeframes defined in `settings.TIMEFRAMES`
- OHLCV calculation: `open=first(mid), high=max(mid), low=min(mid), close=last(mid), tick_count=count()`
- Inserts results into `ihqe.xauusd_ohlcv` with the correct `timeframe` key
- Must handle gaps in tick data (market closed periods) without creating artificial candles
- Callable as: `OHLCVBuilder(db_client).build_all(start_date, end_date)`
- Also callable per-timeframe: `OHLCVBuilder(db_client).build("4H", start_date, end_date)`

### Task 1.6 — Tiingo Live Tick Streamer
File: `ingestion/tiingo_stream.py`

Requirements:
- Class: `TiingoStream`
- Connects to `wss://api.tiingo.com/fx`
- Subscription payload:
```python
{
    "eventName": "subscribe",
    "authorization": TIINGO_API_TOKEN,
    "eventData": {
        "thresholdLevel": TIINGO_THRESHOLD,
        "tickers": [TIINGO_TICKER]
    }
}
```
- Parses incoming messages: `messageType == 'A'` and `data[0][0] == 'Q'`
- Quote tick fields: `ticker=data[0][1], timestamp=data[0][2], bid=data[0][4], ask=data[0][6]`
- Inserts each tick into `ihqe.xauusd_ticks` via `ClickHouseClient`
- Handles heartbeat messages silently (do not insert)
- Auto-reconnects on disconnect with exponential backoff (1s, 2s, 4s, max 30s)
- Runs in a non-blocking background thread via `threading.Thread(daemon=True)`
- Method: `TiingoStream(db_client, api_token).start()` — starts the background thread
- Method: `TiingoStream.stop()` — cleanly closes the WebSocket

### Task 1.7 — Phase 1 Integration Test Script
File: `run_phase1.sh`

Requirements:
```bash
#!/bin/bash
# Phase 1 system startup and validation script
# Run this to verify Phase 1 is fully working

echo "=== IHQE Phase 1 Startup ==="

# 1. Start ClickHouse
docker-compose -f database/docker-compose.yml up -d
sleep 5

# 2. Verify ClickHouse tables exist
python3 -c "
from database.clickhouse_client import ClickHouseClient
db = ClickHouseClient()
tables = db.query_df('SHOW TABLES FROM ihqe')
print('Tables:', tables['name'].tolist())
"

# 3. Run Dukascopy download (last 2 years only for quick test)
# Full download: bash ingestion/dukascopy_downloader.sh
bash ingestion/dukascopy_downloader.sh --years 2 --test

# 4. Load into ClickHouse
python3 -m ingestion.dukascopy_loader

# 5. Build OHLCV tables
python3 -c "
from database.clickhouse_client import ClickHouseClient
from engine.ohlcv_builder import OHLCVBuilder
db = ClickHouseClient()
OHLCVBuilder(db).build_all('2023-01-01', 'today')
print('OHLCV build complete.')
"

# 6. Start Tiingo live stream (runs for 60 seconds as test)
python3 -c "
import time
from database.clickhouse_client import ClickHouseClient
from ingestion.tiingo_stream import TiingoStream
import os
db = ClickHouseClient()
stream = TiingoStream(db, os.getenv('TIINGO_API_TOKEN'))
stream.start()
print('Streaming live ticks for 60 seconds...')
time.sleep(60)
stream.stop()
db2 = ClickHouseClient()
count = db2.query_df('SELECT count() as c FROM ihqe.xauusd_ticks WHERE ts > now() - 120').iloc[0]['c']
print(f'Live ticks received in last 2 minutes: {count}')
"

echo "=== Phase 1 Complete ==="
```

---

## 8. REQUIREMENTS FILE

### `requirements.txt`
```
clickhouse-driver==0.2.7
pandas==2.1.4
numpy==1.26.3
websocket-client==1.7.0
requests==2.31.0
streamlit==1.35.0
plotly==5.19.0
tqdm==4.66.1
python-dotenv==1.0.0
pyarrow==14.0.2
schedule==1.2.1
uuid==1.30
```

Install: `pip install -r requirements.txt`

---

## 9. CODING STANDARDS

Apply these standards to every file in the project without exception.

### Naming
- All database column names: `snake_case`
- All Python classes: `PascalCase`
- All Python functions and variables: `snake_case`
- All constants in `settings.py`: `UPPER_SNAKE_CASE`
- Timeframe keys: always use the canonical keys from `settings.TIMEFRAMES` — `"12M"`, `"3M"`, `"1M"`, `"W"`, `"4H"`, `"1H"`
- Direction values: always lowercase string `"bullish"` or `"bearish"` — never `"LONG"`, `"long"`, `"BUY"`, etc.
- Signal types: always one of: `"macro_alert"`, `"mid_alert"`, `"active"`, `"flip"`, `"execute"`
- Trade types: always one of: `"primary"`, `"counter_trend"`

### Error Handling
- Every database operation: wrapped in try/except with specific ClickHouse exceptions caught
- Every WebSocket operation: wrapped in try/except with reconnection logic
- Every file read operation: check file exists before reading, raise descriptive error if not
- Never use bare `except:` — always catch specific exception types
- Log all errors with `logging.error(f"...: {e}")` — never use `print()` for errors

### Logging
```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)
```
Use `logger.info()`, `logger.warning()`, `logger.error()` — never `print()` except in test scripts.

### Type Hints
All function signatures must include type hints:
```python
def detect_bullish_fvg(candles: pd.DataFrame, timeframe: str) -> list[dict]:
```

### Testing
- Every core algorithm function must have a unit test in `tests/`
- Tests use `pytest`
- Tests must not require a live database connection — use mock data fixtures
- Run tests: `pytest tests/ -v`

### No Hardcoded Values
- All asset names, URLs, thresholds come from `config/settings.py`
- Never hardcode `"xauusd"`, `"localhost"`, `9000`, etc. directly in module code

---

## 10. PHASE GATE CHECKLIST

Before declaring Phase 1 complete, verify every item:

```
Phase 1 Checklist:
[ ] docker-compose up starts ClickHouse without errors
[ ] All 8 tables exist in ihqe database with correct schemas
[ ] dukascopy_downloader.sh downloads at least 2 years of XAU/USD data to CSV
[ ] dukascopy_loader.py loads CSV data into xauusd_ticks table
[ ] xauusd_ohlcv table contains data for all 6 timeframes
[ ] tiingo_stream.py connects and receives live ticks for 60+ seconds without disconnect
[ ] Live ticks appear in xauusd_ticks table within 5 seconds of receipt
[ ] ClickHouseClient retry logic tested — survives a 5 second database outage
[ ] run_phase1.sh completes without errors
[ ] pytest tests/ -v passes all tests
[ ] No hardcoded credentials anywhere in the codebase
```

---

## 11. WHAT NOT TO BUILD IN PHASE 1

Do not write any code for the following until Phase 1 checklist is 100% complete:
- FVG detection (`engine/fvg_detector.py`)
- Fibonacci calculator (`engine/fibonacci.py`)
- Cascade state machine (`engine/cascade.py`)
- Double trade detection (`engine/double_trade.py`)
- Signal engine (`engine/signal_engine.py`)
- Any sniper module (`sniper/`)
- Any dashboard module (`dashboard/`)

These belong to Phase 2, 3, and 4 respectively. Building them early without Phase 1 data infrastructure causes rework.

---

## 12. QUICK REFERENCE — KEY FACTS

| Item | Value |
|---|---|
| Asset | XAU/USD (Spot Gold CFD) |
| Historical data start | 2003-01-01 |
| Historical data source | Dukascopy (free, no login) |
| Live data source | Tiingo WebSocket API (free tier) |
| Live data type | Top-of-Book Bid/Ask quote ticks |
| Database | ClickHouse running in Docker |
| Timeframe cascade order | 12M → 3M → 1M → W → 4H → 1H |
| FVG minimum size | Any gap > 0 ticks qualifies |
| FVG priority rule | First FVG in zone = Extreme FVG (takes priority) |
| Discount zone | Price below 0.5 Fibonacci level |
| Premium zone | Price above 0.5 Fibonacci level |
| Long sniper zone | 0.5 to 0.618 |
| Short sniper zone | 0.5 to 0.382 |
| Zone entry trigger | Intrabar — no candle close required |
| CT cascade activation | When primary cascade has 3+ confirmed gates |
| CT exit target | Primary macro 0.5 level |
| CT grid validity | CT top/bottom must be within 3% of primary 0.5 |

---

*IHQE v2.1 — Agent Prompt v1.0 — Internal Use Only*
