# IHQE v3.0 — Corrected Master Agent Prompt
## Complete System Rebuild Instructions

---

## 0. CRITICAL — READ BEFORE TOUCHING ANY CODE

This document **replaces** `IHQE_AGENT_PROMPT.md` entirely.

The previous build (v2.1) had three fundamental architectural errors that
must be corrected before any new code is written:

**Error 1 — Wrong cascade depth.**
The system built a 6-timeframe cascade (12M → 3M → 1M → W → 4H → 1H).
The actual swing trade cascade is **3 tiers only**: 12M → 3M → 1M.
The entry is taken at the 1-Month level, not the 1-Hour.

**Error 2 — Missing BOS prerequisite.**
The system drew Fibonacci grids without confirming a Break of Structure first.
BOS must be confirmed on the 12-Month chart before any cascade begins.
No BOS = no Fibonacci = no cascade. This is non-negotiable.

**Error 3 — Wrong FVG filtering.**
The system detected 122,243 FVGs because it scanned all candles everywhere.
FVGs are only valid inside an active discount or premium zone, on the
3-Month and 1-Month timeframes only. The 12-Month uses BOS, not FVG.

All engine modules (cascade.py, fvg_detector.py, fibonacci.py,
signal_engine.py, double_trade.py) must be rewritten from scratch.
The data infrastructure (ClickHouse, Dukascopy loader, Tiingo stream,
OHLCV builder) is correct and does not need changes.
The dashboard must be rebuilt from Streamlit to React + FastAPI.

---

## 1. WHAT WE ARE BUILDING

The IHQE is a two-layer automated trading platform for Spot Gold (XAU/USD):

**Layer 1 — Swing Trade Engine (Primary)**
A 3-tier top-down cascade: 12-Month → 3-Month → 1-Month.
Identifies high-probability swing setups with multi-month hold periods.
Entry at 1-Month discount zone. Target at 12-Month swing high.
Stop loss below 1-Month swing low.
Generates signals days to months before the entry window opens.

**Layer 2 — Scalp Trade Engine (Secondary)**
Uses 4-Hour and 1-Hour timeframes to generate short-term trades
that run inside the confirmed swing structure.
Two types of scalp trades:
- Path scalps: counter-trend entries riding price TOWARD the 1M discount zone
- Continuation scalps: entries riding price FROM the 1M zone TOWARD the 12M target
The scalp layer only activates after the swing cascade has at least
2 of 3 swing gates confirmed.

**Dashboard**
React frontend + FastAPI backend + TradingView Lightweight Charts.
Shows all historical setups from 2003 to present plus live current state.
Three panels: Historical State Map, Cascade Status, Signal Board.

---

## 2. THE EXACT STRATEGY RULES

### 2.1 STEP 1 — 12-Month BOS Confirmation

```
RULE: No BOS on 12-Month = nothing happens. Full stop.

BOS DEFINITION (Bullish):
  A candle CLOSES above the most recent significant swing high
  on the 12-Month chart.
  The swing high is defined as: the highest high in the 3 candles
  immediately preceding the current move.

BOS DEFINITION (Bearish):
  A candle CLOSES below the most recent significant swing low
  on the 12-Month chart.
  The swing low is defined as: the lowest low in the 3 candles
  immediately preceding the current move.

AFTER BULLISH BOS CONFIRMED:
  Draw Fibonacci from:
    Point A (swing_low)  = lowest low of the leg that preceded the BOS
    Point B (swing_high) = highest high after the BOS candle closes
  Mark the 12-Month Discount Zone = everything below the 0.5 level.

AFTER BEARISH BOS CONFIRMED:
  Draw Fibonacci from:
    Point A (swing_high) = highest high of the leg that preceded the BOS
    Point B (swing_low)  = lowest low after the BOS candle closes
  Mark the 12-Month Premium Zone = everything above the 0.5 level.

NOTE: On the 12-Month chart, NO FVG is required.
BOS confirmation alone is sufficient to draw the grid.
```

### 2.2 STEP 2 — Wait for Price to Enter 12-Month Zone

```
RULE: Do not look at the 3-Month chart until this condition is met.

BULLISH: Live price ticks BELOW the 12-Month 0.5 level (intrabar, no close needed)
BEARISH: Live price ticks ABOVE the 12-Month 0.5 level (intrabar, no close needed)

When this condition is met:
  - 12-Month gate status → 'zone_entered'
  - Begin monitoring the 3-Month chart
```

### 2.3 STEP 3 — 3-Month FVG Formation

```
RULE: Wait for an FVG to form on the 3-Month chart
      while price is inside the 12-Month discount/premium zone.

FVG DEFINITION (Bullish, for discount zone):
  3 consecutive candles where:
    candle[2].low > candle[0].high
  Gap top    = candle[2].low
  Gap bottom = candle[0].high
  Wick rule  = candle[1].low must NOT go below candle[0].low
  Any gap size qualifies (even 1 tick)
  Use the FIRST FVG that forms (Extreme FVG) — ignore subsequent ones

FVG DEFINITION (Bearish, for premium zone):
  3 consecutive candles where:
    candle[2].high < candle[0].low
  Gap top    = candle[0].low
  Gap bottom = candle[2].high
  Wick rule  = candle[1].high must NOT go above candle[0].high

AFTER 3-MONTH FVG CONFIRMED:
  Draw Fibonacci on the 3-Month chart:
    Point A = lowest low of the structural leg that created the FVG
              (scan back up to 12 candles before the FVG candle[0])
    Point B = highest high after the FVG formation
              (scan forward up to 6 candles after candle[2])
  Mark 3-Month Discount Zone = below the 3-Month 0.5 level
  3-Month gate status → 'fvg_confirmed'
```

### 2.4 STEP 4 — Wait for Price to Enter 3-Month Zone

```
RULE: Do not look at the 1-Month chart until this condition is met.

BULLISH: Live price ticks BELOW the 3-Month 0.5 level
BEARISH: Live price ticks ABOVE the 3-Month 0.5 level

When this condition is met:
  - 3-Month gate status → 'zone_entered'
  - Begin monitoring the 1-Month chart
```

### 2.5 STEP 5 — 1-Month FVG Formation

```
RULE: Same as Step 3 but on the 1-Month chart,
      while price is inside the 3-Month discount/premium zone.

Same FVG detection rules apply.

AFTER 1-MONTH FVG CONFIRMED:
  Draw Fibonacci on the 1-Month chart:
    Point A = lowest low of the structural leg (scan back 6 candles)
    Point B = highest high after FVG (scan forward 3 candles)
  Mark 1-Month Discount Zone = below the 1-Month 0.5 level
  1-Month gate status → 'fvg_confirmed'
```

### 2.6 STEP 6 — Entry, Stop Loss, Take Profit

```
ENTRY TRIGGER:
  Price enters the 1-Month discount zone (ticks below 1-Month 0.5)
  All 3 swing gates must be confirmed before entry is valid.

ENTRY TYPE: Market order at current price when zone is entered.

STOP LOSS:
  Below the 1-Month swing low = the 0.0 level of the 1-Month Fibonacci grid.

TAKE PROFIT:
  The 12-Month swing high = the 1.0 level of the 12-Month Fibonacci grid.

SIGNAL CLASSIFICATION:
  - 'macro_alert'  : 12-Month BOS confirmed, grid drawn, waiting for zone
  - 'mid_alert'    : 12-Month zone entered AND 3-Month FVG confirmed
  - 'active'       : All 3 gates confirmed, price entering 1-Month zone
  - 'execute'      : Entry fired
  - 'closed'       : Price hit take profit or stop loss
```

---

## 3. SCALP LAYER RULES

### 3.1 Activation Condition

```
Scalp layer activates when: swing cascade gates_confirmed >= 2
(At minimum, 12-Month BOS confirmed + 12-Month zone entered)

Two types of scalp trades run simultaneously:
  Type A — Path Scalps  : Short trades riding price DOWN to the 1M zone
  Type B — Continuation : Long trades riding price UP from the 1M zone
```

### 3.2 Path Scalp Rules (Type A)

```
Context: Swing is bullish (price falling toward 1M discount zone).
Scalp direction: SHORT (counter-trend, riding the drop).

TIMEFRAMES: 4-Hour and 1-Hour independently.

DETECTION:
  On 4H chart: Wait for a Bearish FVG inside a 4H premium zone.
  4H premium zone = the 4H Fibonacci drawn from the most recent
  4H BOS swing low to swing high. Premium = above 0.5.

  On 1H chart: Same logic on 1-Hour candles.

ENTRY: When price enters the 4H or 1H premium zone (above 0.5).
STOP:  Above the 4H or 1H swing high (1.0 level of that grid).
TARGET: The nearest 4H or 1H discount zone below current price.
         If none exists, target is the 1-Month 0.5 level.

INVALIDATION: If swing cascade detects the 1-Month entry signal,
  all open path scalp shorts are immediately closed.
```

### 3.3 Continuation Scalp Rules (Type B)

```
Context: 1-Month entry has been taken. Price moving UP toward 12M target.
Scalp direction: LONG (with the swing, re-entries on pullbacks).

TIMEFRAMES: 4-Hour and 1-Hour independently.

DETECTION:
  On 4H chart: Wait for a Bullish FVG inside a 4H discount zone.
  4H discount zone = below 0.5 of the most recent bullish 4H grid.

  On 1H chart: Same logic on 1-Hour candles.

ENTRY: When price enters the 4H or 1H discount zone (below 0.5).
STOP:  Below the 4H or 1H swing low (0.0 level of that grid).
TARGET: The next 4H resistance level or the 12-Month swing high.

INVALIDATION: If price closes below the 1-Month swing low (swing stop hit),
  all continuation scalps are immediately closed.
```

---

## 4. CORRECTED DATABASE SCHEMA CHANGES

Keep all existing tables. Add/modify the following:

```sql
-- Modify cascade_states to reflect 3-tier swing + scalp layers
ALTER TABLE ihqe.cascade_states ADD COLUMN IF NOT EXISTS
  layer String DEFAULT 'swing';
  -- 'swing' = 12M/3M/1M primary cascade
  -- 'scalp_path' = 4H/1H path scalp
  -- 'scalp_cont' = 4H/1H continuation scalp

-- Add BOS events table (new — was missing entirely)
CREATE TABLE IF NOT EXISTS ihqe.bos_events
(
    bos_id          String,
    timeframe       String,
    direction       String,         -- 'bullish' | 'bearish'
    bos_candle_ts   DateTime64(3, 'UTC'),
    broken_level    Float64,        -- the swing high/low that was broken
    bos_close       Float64,        -- closing price of the BOS candle
    swing_low       Float64,        -- Point A for Fibonacci
    swing_high      Float64,        -- Point B for Fibonacci
    is_active       UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree()
ORDER BY (timeframe, bos_candle_ts);

-- Add trade outcomes table for both swing and scalp
CREATE TABLE IF NOT EXISTS ihqe.trades
(
    trade_id        String,
    signal_id       String,
    trade_type      String,         -- 'swing' | 'scalp_path' | 'scalp_cont'
    direction       String,         -- 'long' | 'short'
    timeframe       String,         -- execution timeframe
    entry_price     Float64,
    stop_loss       Float64,
    take_profit     Float64,
    entry_ts        DateTime64(3, 'UTC'),
    exit_price      Nullable(Float64),
    exit_ts         Nullable(DateTime64(3, 'UTC')),
    exit_reason     String DEFAULT '',  -- 'take_profit' | 'stop_loss' | 'invalidated'
    pnl_pct         Nullable(Float64),
    status          String DEFAULT 'open'
)
ENGINE = ReplacingMergeTree()
ORDER BY (trade_type, entry_ts);
```

---

## 5. CORRECTED ENGINE MODULE SPECIFICATIONS

### 5.1 `engine/bos_detector.py` (NEW — build first)

```python
class BOSDetector:
    """
    Detects Break of Structure on a given timeframe.
    Must be run before FVG detection or Fibonacci calculation.
    """

    def detect(self, candles: pd.DataFrame, timeframe: str) -> list[dict]:
        """
        Scans candles and returns all BOS events.

        BOS Bullish:
          current candle closes above the highest high
          of the 3 candles immediately before it.

        BOS Bearish:
          current candle closes below the lowest low
          of the 3 candles immediately before it.

        Returns list of dicts with keys:
          bos_id, timeframe, direction, bos_candle_ts,
          broken_level, bos_close, swing_low, swing_high
        """

    def get_active_bos(self, timeframe: str) -> dict | None:
        """
        Returns the most recent unbroken BOS event for this timeframe.
        A BOS is 'broken' when price closes beyond the swing_low (bullish)
        or swing_high (bearish) of the grid it created.
        """
```

### 5.2 `engine/fvg_detector.py` (REWRITE)

```python
class FVGDetector:
    """
    Detects FVGs ONLY inside active discount/premium zones.
    Must receive the active Fibonacci grid for context.
    Only valid on 3-Month and 1-Month timeframes for swing trades.
    Valid on 4H and 1H for scalp trades.
    """

    def detect_in_zone(
        self,
        candles: pd.DataFrame,
        timeframe: str,
        zone_upper: float,  # 0.5 level of parent grid
        zone_lower: float,  # 0.0 level of parent grid (swing low)
        direction: str      # 'bullish' | 'bearish'
    ) -> list[dict]:
        """
        Scans for FVGs where the FVG itself is located
        INSIDE the zone boundaries [zone_lower, zone_upper].

        For bullish: only flag FVGs where gap_bottom >= zone_lower
                     and gap_top <= zone_upper
        For bearish: only flag FVGs where gap_top <= zone_upper (premium)
                     and gap_bottom >= zone_lower

        Returns only the FIRST qualifying FVG (Extreme FVG).
        Subsequent FVGs in the same zone are stored but is_extreme = 0.
        """
```

### 5.3 `engine/fibonacci.py` (REWRITE)

```python
class FibonacciCalculator:
    """
    Calculates Fibonacci grids anchored to BOS-defined swing points.
    """

    def calculate(
        self,
        swing_low: float,
        swing_high: float,
        direction: str,     # 'bullish' | 'bearish'
        timeframe: str,
        anchor_event_id: str  # bos_id or fvg_id that triggered this grid
    ) -> dict:
        """
        Returns dict with all 7 levels plus zone boundaries.
        For bullish: levels count UP from swing_low.
        For bearish: levels count DOWN from swing_high.

        All level keys use snake_case:
          level_0_000, level_0_236, level_0_382,
          level_0_500, level_0_618, level_0_786, level_1_000

        discount_zone_upper = level_0_500  (price must be below this for longs)
        sniper_zone_deep    = level_0_618  (deepest expected retracement for longs)
        premium_zone_lower  = level_0_500  (price must be above this for shorts)
        sniper_zone_short   = level_0_382  (deepest expected rally for shorts)
        """

    def is_in_discount_zone(self, price: float, grid: dict) -> bool:
        """Returns True if price is below grid['level_0_500'] (bullish)"""

    def is_in_premium_zone(self, price: float, grid: dict) -> bool:
        """Returns True if price is above grid['level_0_500'] (bearish)"""

    def is_grid_valid(self, price: float, grid: dict) -> bool:
        """
        Bullish grid invalid if price closes below level_0_000 (swing low).
        Bearish grid invalid if price closes above level_0_000 (swing high).
        """
```

### 5.4 `engine/cascade.py` (REWRITE)

```python
class SwingCascade:
    """
    Manages the 3-tier swing cascade: 12M → 3M → 1M.
    Each gate is strictly sequential — parent must confirm before child opens.
    """

    SWING_TIMEFRAMES = ['12M', '3M', '1M']

    def process_bar(self, timeframe: str, candle: dict, live_price: float):
        """
        Called on every new candle for the given timeframe.
        Updates gate states and emits signals when transitions occur.

        Gate transition rules:
          12M: 'waiting' → 'bos_confirmed' (BOSDetector fires)
               'bos_confirmed' → 'zone_entered' (price ticks below 0.5)

          3M:  Only begins when 12M is 'zone_entered'
               'waiting' → 'fvg_confirmed' (FVGDetector fires inside 12M zone)
               'fvg_confirmed' → 'zone_entered' (price ticks below 3M 0.5)

          1M:  Only begins when 3M is 'zone_entered'
               'waiting' → 'fvg_confirmed' (FVGDetector fires inside 3M zone)
               'fvg_confirmed' → 'zone_entered' → emit 'active' signal
        """

    def get_gates_confirmed(self) -> int:
        """
        Returns count of gates with status in
        ('bos_confirmed', 'fvg_confirmed', 'zone_entered').
        Maximum 3 for swing cascade.
        """

    def get_current_signal_type(self) -> str | None:
        """Returns signal type based on gates_confirmed count."""

    def is_entry_valid(self) -> bool:
        """True only when all 3 gates are confirmed AND 1M zone is entered."""

    def get_stop_loss(self) -> float:
        """Returns the 1M grid level_0_000 (swing low)."""

    def get_take_profit(self) -> float:
        """Returns the 12M grid level_1_000 (swing high)."""


class ScalpLayer:
    """
    Manages 4H and 1H scalp detection inside confirmed swing structure.
    Only activates when SwingCascade.get_gates_confirmed() >= 2.
    """

    SCALP_TIMEFRAMES = ['4H', '1H']

    def process_bar(self, timeframe: str, candle: dict,
                    swing_cascade: SwingCascade):
        """
        Detects scalp setups on 4H and 1H.
        Uses the same BOS → FVG → Fibonacci logic as swing cascade
        but on lower timeframes.
        Determines scalp type based on swing context:
          - If swing 1M entry not yet taken: scalp_path (short)
          - If swing 1M entry taken: scalp_cont (long)
        """
```

### 5.5 `engine/signal_engine.py` (REWRITE)

```python
class SignalEngine:
    """
    Classifies and publishes signals for both swing and scalp layers.
    """

    def classify_swing(self, gates_confirmed: int,
                        price_in_1m_zone: bool) -> str | None:
        levels = {
            0: None,
            1: 'macro_alert',   # 12M BOS confirmed
            2: 'mid_alert',     # 12M zone + 3M FVG confirmed
            3: 'active',        # All 3 gates confirmed
        }
        if price_in_1m_zone and gates_confirmed == 3:
            return 'execute'
        return levels.get(gates_confirmed)

    def classify_scalp(self, scalp_type: str,
                        gates_confirmed: int) -> str | None:
        """
        Scalp signals only published when swing gates_confirmed >= 2.
        scalp_type: 'path' | 'continuation'
        """
```

---

## 6. DASHBOARD REBUILD — REACT + FASTAPI

### 6.1 Backend — FastAPI

File: `api/main.py`

```python
# FastAPI serves ClickHouse data to the React frontend.
# All heavy computation (BOS detection, FVG scanning, cascade state)
# is done by the Python engine and stored in ClickHouse.
# FastAPI only reads from ClickHouse and formats for the frontend.

# Required endpoints:

GET /api/ohlcv/{timeframe}?start={date}&end={date}
# Returns OHLCV candles as JSON array for TradingView chart

GET /api/fvg/{timeframe}?start={date}&end={date}
# Returns all FVG rectangles (active and mitigated) for overlay

GET /api/fib_grids/{timeframe}?active_only=true
# Returns Fibonacci grid levels for overlay lines

GET /api/bos_events/{timeframe}
# Returns BOS markers for the chart

GET /api/cascade/current
# Returns live cascade gate states for all timeframes

GET /api/signals?type=swing&status=open
# Returns current trade signals

GET /api/signals/history?limit=50
# Returns historical signal outcomes

GET /api/live/price
# WebSocket endpoint streaming live XAU/USD price from Tiingo
```

### 6.2 Frontend Structure

```
dashboard/
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── App.jsx                  # Main layout, tab navigation
│   │   ├── components/
│   │   │   ├── ChartPanel.jsx       # TradingView Lightweight Charts wrapper
│   │   │   ├── FVGOverlay.jsx       # Renders FVG rectangles on chart
│   │   │   ├── FibOverlay.jsx       # Renders Fibonacci lines on chart
│   │   │   ├── BOSMarker.jsx        # Renders BOS arrows on chart
│   │   │   ├── CascadeStatus.jsx    # Gate status cards (Panel 2)
│   │   │   └── SignalBoard.jsx      # Signal cards with linked pairs (Panel 3)
│   │   ├── hooks/
│   │   │   ├── useOHLCV.js          # Fetches candle data from FastAPI
│   │   │   ├── useCascade.js        # Polls cascade state every 5 seconds
│   │   │   └── useLivePrice.js      # WebSocket hook for live price
│   │   └── api/
│   │       └── client.js            # Axios instance pointing to FastAPI
└── api/
    ├── main.py                      # FastAPI app
    └── routers/
        ├── ohlcv.py
        ├── signals.py
        ├── cascade.py
        └── live.py
```

### 6.3 TradingView Lightweight Charts Integration

```javascript
// Install: npm install lightweight-charts

import { createChart } from 'lightweight-charts';

// Each ChartPanel renders one timeframe.
// Overlays are added as series on top of the candlestick series.

// FVG rectangles: use chart.addRectangle() with opacity 0.3
//   Bullish FVG: green fill, solid border
//   Bearish FVG: red fill, solid border
//   Mitigated FVG: same color but opacity 0.1

// Fibonacci lines: use chart.addLineSeries() for each level
//   0.5 level: white, dashed, lineWidth 2
//   0.618 level: gold (#B8860B), solid, lineWidth 1
//   0.382 level: gold (#B8860B), solid, lineWidth 1
//   Others: gray, dashed, lineWidth 1

// Discount zone shading: addRectangle() from 0.5 to 0.0, green opacity 0.08
// Premium zone shading: addRectangle() from 0.5 to 1.0, red opacity 0.08

// BOS markers: addMarkers() with arrow shape on the BOS candle
//   Bullish BOS: green upward arrow below candle
//   Bearish BOS: red downward arrow above candle

// All 6 timeframe charts share the same zoom/pan timeline
// when the user holds Shift and scrolls.
```

### 6.4 Color Scheme

```
Background:       #0D0D0D  (near-black)
Panel background: #141414
Border:           #2A2A2A
Text primary:     #FFFFFF
Text secondary:   #888888
Gold accent:      #B8860B
Bullish green:    #26A69A
Bearish red:      #EF5350
FVG bullish fill: #26A69A at 30% opacity
FVG bearish fill: #EF5350 at 30% opacity
Discount zone:    #26A69A at 8% opacity
Premium zone:     #EF5350 at 8% opacity
Gate confirmed:   #26A69A
Gate waiting:     #444444
Gate active:      #B8860B (pulsing animation)
```

---

## 7. BUILD ORDER — STRICT SEQUENCE

Do not skip steps. Do not build ahead.

```
STEP 1: engine/bos_detector.py
  - Build BOSDetector class
  - Unit tests with synthetic 12M candles
  - Verify BOS events stored correctly in ihqe.bos_events

STEP 2: engine/fibonacci.py (rewrite)
  - Anchor to BOS swing points instead of arbitrary highs/lows
  - All 7 levels calculated correctly
  - Unit tests verifying level math

STEP 3: engine/fvg_detector.py (rewrite)
  - Zone-filtered detection only
  - Extreme FVG flagging
  - Unit tests: verify FVGs outside zone are NOT returned
  - Target: < 50 FVGs detected per timeframe across 22 years on 3M chart

STEP 4: engine/cascade.py (rewrite)
  - SwingCascade: sequential 3-gate state machine
  - ScalpLayer: 4H/1H detection with swing context awareness
  - Integration test: run on 2 years of real XAU/USD OHLCV data
  - Expected output: 1-3 swing signals per year (not hundreds)

STEP 5: engine/signal_engine.py (rewrite)
  - Swing signal classification
  - Scalp signal classification
  - Linked signal pairs for double trades
  - Historical backtest run across all 22 years of data
  - Verify signal prices are historically plausible (not $340 or $1,766)

STEP 6: api/main.py (NEW)
  - FastAPI with all 6 endpoints listed in Section 6.1
  - Run with: uvicorn api.main:app --reload --port 8000
  - Test each endpoint returns correct data before building frontend

STEP 7: dashboard/frontend/ (NEW)
  - React app with TradingView Lightweight Charts
  - Build Panel 1 (Historical State Map) first and verify FVGs/Fibs visible
  - Then Panel 2 (Cascade Status)
  - Then Panel 3 (Signal Board)
  - Run with: npm start (proxies API calls to localhost:8000)

STEP 8: Integration validation
  - Open Panel 1 on 1-Month chart
  - The FVG rectangles and Fibonacci grids visible must match
    the TradingView charts in the strategy document screenshots
  - If they do not match visually: debug fibonacci.py swing anchors first
```

---

## 8. VALIDATION CRITERIA

The build is only complete when ALL of these pass:

```
Engine validation:
[ ] 12M BOS detection identifies the correct BOS on XAU/USD history
    (verify against strategy document screenshot — BOS visible ~2009)
[ ] 12M Fibonacci grid spans from the 2008 swing low to the 2020 swing high
    (approximately $680 to $2,075)
[ ] 3M FVG detected inside 12M discount zone around 2015-2016
    (visible in strategy document screenshot as blue rectangle ~$1,050-1,100)
[ ] 1M FVG detected inside 3M discount zone
[ ] Signal classified as 'active' with entry around $1,100-$1,200
[ ] Take profit target = 12M swing high ~$2,075
[ ] Stop loss = 1M swing low

Dashboard validation:
[ ] Panel 1 shows candlestick charts for all 6 timeframes (3 swing + 3 scalp)
[ ] Green FVG rectangles visible inside discount zones only
[ ] Fibonacci lines drawn at correct price levels
[ ] BOS arrows appear on the correct candles
[ ] Panel 2 shows current cascade gate states correctly
[ ] Panel 3 shows active signals with entry, SL, TP prices
[ ] Live price updates visible in real time

Performance validation:
[ ] Dashboard loads in under 3 seconds
[ ] Chart panning and zooming is smooth (no lag)
[ ] Live price updates every 1-2 seconds
```

---

## 9. WHAT TO KEEP FROM THE PREVIOUS BUILD

```
KEEP (no changes needed):
  database/docker-compose.yml
  database/init_schema.sql        (add bos_events and trades tables only)
  database/clickhouse_client.py
  ingestion/dukascopy_downloader.sh
  ingestion/dukascopy_loader.py
  ingestion/tiingo_stream.py
  engine/ohlcv_builder.py
  requirements.txt                (add: fastapi, uvicorn, react deps)

DELETE AND REBUILD FROM SCRATCH:
  engine/fvg_detector.py
  engine/fibonacci.py
  engine/cascade.py
  engine/double_trade.py
  engine/signal_engine.py
  dashboard/ (entire folder — replace with React frontend + FastAPI)

CREATE NEW:
  engine/bos_detector.py
  api/main.py
  api/routers/
  dashboard/frontend/
```

---

## 10. QUICK REFERENCE

| Parameter | Value |
|---|---|
| Asset | XAU/USD Spot Gold CFD |
| Swing cascade | 12-Month → 3-Month → 1-Month |
| Scalp timeframes | 4-Hour + 1-Hour |
| 12M trigger | BOS confirmation (candle close, no FVG needed) |
| 3M/1M trigger | FVG inside parent discount/premium zone |
| FVG priority | First FVG in zone (Extreme FVG) |
| FVG size minimum | Any gap > 0 ticks |
| Zone entry trigger | Intrabar — no close required |
| Entry | Price ticks into 1-Month discount/premium zone |
| Stop loss | 1-Month swing low (0.0 level) |
| Take profit | 12-Month swing high (1.0 level) |
| Scalp activation | Swing gates_confirmed >= 2 |
| Dashboard frontend | React + TradingView Lightweight Charts |
| Dashboard backend | FastAPI + ClickHouse |
| Historical data | Dukascopy, 2003–present, 22 years |
| Live data | Tiingo WebSocket, xauusd, thresholdLevel 5 |

---

*IHQE v3.0 — Corrected Master Agent Prompt — Internal Use Only*
