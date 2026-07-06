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
    anchor_event_id String,         -- bos_id or fvg_id that triggered this grid
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

-- ── Break of Structure events ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ihqe.bos_events
(
    bos_id          String,
    timeframe       String,
    direction       String,         -- 'bullish' | 'bearish'
    bos_candle_ts   DateTime64(3, 'UTC'),
    broken_level    Float64,        -- the swing high/low that was broken
    bos_close       Float64,        -- closing price of the BOS candle
    swing_low       Float64,        -- Point A for Fibonacci
    swing_low_ts    DateTime64(3, 'UTC'),
    swing_high      Float64,        -- Point B for Fibonacci
    swing_high_ts   DateTime64(3, 'UTC'),
    is_active       UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree()
ORDER BY (timeframe, bos_candle_ts);

-- ── Cascade gate states ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ihqe.cascade_states
(
    state_id        String,         -- UUID
    cascade_type    String,         -- 'primary' | 'counter_trend'
    direction       String,         -- 'bullish' | 'bearish'
    timeframe       String,
    gate_status     String,         -- 'waiting' | 'bos_confirmed' | 'fvg_confirmed' | 'zone_entered'
    confirmed_at    Nullable(DateTime64(3, 'UTC')),
    fvg_id          Nullable(String),
    grid_id         Nullable(String),
    layer           String DEFAULT 'swing',  -- 'swing' | 'scalp_path' | 'scalp_cont'
    ts_updated      DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(ts_updated)
ORDER BY (cascade_type, direction, timeframe);

-- ── Trade signals ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ihqe.trade_signals
(
    signal_id       String,         -- UUID
    signal_type     String,         -- 'macro_alert' | 'mid_alert' | 'active' | 'execute' | 'closed'
    trade_type      String,         -- 'swing' | 'scalp_path' | 'scalp_cont'
    direction       String,         -- 'long' | 'short'
    gates_confirmed UInt8,          -- how many of 3 swing gates are open
    target_upper    Float64,        -- upper boundary of entry zone
    target_lower    Float64,        -- lower boundary of entry zone
    linked_signal_id Nullable(String),
    published_at    DateTime64(3, 'UTC'),
    status          String DEFAULT 'open'  -- 'open' | 'executed' | 'invalidated'
)
ENGINE = ReplacingMergeTree(published_at)
ORDER BY (signal_type, published_at);

-- ── Trade outcomes (swing + scalp) ─────────────────────────────────────────────
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
