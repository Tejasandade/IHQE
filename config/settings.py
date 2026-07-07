import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# ── Tiingo API ──────────────────────────────────────────────────────────────
TIINGO_API_TOKEN = os.getenv("TIINGO_API_TOKEN")
TIINGO_WS_URL    = "wss://api.tiingo.com/fx"
TIINGO_TICKER    = "xauusd"
TIINGO_THRESHOLD = 5  # Filter level — suppresses micro-pip noise

# ── ClickHouse ──────────────────────────────────────────────────────────────
CH_HOST     = os.getenv("CH_HOST", "localhost")
CH_PORT     = int(os.getenv("CH_PORT", 9000))
CH_HTTP_PORT = int(os.getenv("CH_HTTP_PORT", 8123))
CH_DATABASE = "ihqe"
CH_USER     = os.getenv("CH_USER", "default")
CH_PASSWORD = os.getenv("CH_PASSWORD", "")

# ── Asset ────────────────────────────────────────────────────────────────────
ASSET          = "XAUUSD"
HISTORY_START  = "2003-01-01"
HISTORY_END    = "today"  # Resolved at runtime

# ── Auth / PostgreSQL ────────────────────────────────────
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", 5432))
PG_DATABASE = os.getenv("PG_DATABASE", "ihqe")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "ihqe_secret")

INTELLIGENCE_WEIGHTS = {'12M': 5.0, '3M': 3.0, '1M': 2.0, '4H': 1.5, '1H': 1.0}
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key-for-dev")
JWT_EXPIRE_MINUTES = 60
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@ihqe.io")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# ── Timeframe definitions ─────────────────────────────────────────────────────
# Keys are used as canonical identifiers throughout the entire codebase
TIMEFRAMES = {
    "12M":  {"label": "12-Month",  "dukascopy_interval": "mn1",  "resample_rule": "Y"},
    "3M":   {"label": "3-Month",   "dukascopy_interval": "mn1",  "resample_rule": "Q"},
    "1M":   {"label": "1-Month",   "dukascopy_interval": "mn1",  "resample_rule": "M"},
    "W":    {"label": "Weekly",    "dukascopy_interval": "w1",   "resample_rule": "W-MON"},
    "4H":   {"label": "4-Hour",    "dukascopy_interval": "h4",   "resample_rule": "4h"},
    "1H":   {"label": "1-Hour",    "dukascopy_interval": "h1",   "resample_rule": "1h"},
}
TIMEFRAME_CASCADE = ["12M", "3M", "1M", "W", "4H", "1H"]  # Ordered top to bottom

# ── v3 Cascade definitions ──────────────────────────────────────────────────
SWING_CASCADE = ["12M", "3M", "1M"]       # 3-tier swing cascade
SCALP_TIMEFRAMES = ["4H", "1H"]           # Scalp layer timeframes

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

# ── BOS Detector ─────────────────────────────────────────
BOS_SWING_LEG_LOOKBACK = 12
BOS_SWING_FORWARD_SCAN = 6
BOS_FRACTAL_SIDE = {"12M": 3, "3M": 3, "default": 2}
BOS_PCT_THRESHOLDS = {"12M": 3.0, "3M": 2.0, "1M": 1.0, "W": 1.0, "4H": 0.7, "1H": 0.5}

# ── FVG Detector ─────────────────────────────────────────
# (no hardcoded values currently — FVG detection is pure price logic)

# ── Fibonacci Calculator ─────────────────────────────────
FIB_GRID_LOOKBACK = {"3M": 12, "1M": 6, "default": 12}
FIB_GRID_FORWARD = {"3M": 6, "1M": 3, "default": 6}

# ── Scalp layer settings ───────────────────────────────────────────────────
SCALP_ACTIVATION_GATES = 2  # Minimum swing cascade gates before scalp layer activates

# ── Data paths ───────────────────────────────────────────────────────────────
import pathlib
PROJECT_ROOT = pathlib.Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
HISTORICAL_DIR = DATA_DIR / "historical" / "xauusd"
PROCESSED_DIR = DATA_DIR / "processed"
