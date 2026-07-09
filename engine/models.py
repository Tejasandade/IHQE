from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class BosEvent(BaseModel):
    bos_id: str
    timeframe: str
    direction: str
    bos_candle_ts: datetime
    broken_level: float
    bos_close: float
    swing_low: float
    swing_low_ts: datetime
    swing_high: float
    swing_high_ts: datetime
    is_active: int

class FibGrid(BaseModel):
    grid_id: str
    timeframe: str
    direction: str
    anchor_event_id: str
    swing_low_ts: datetime
    swing_high_ts: datetime
    swing_low: float
    swing_high: float
    total_range: float
    level_1_000: float
    level_0_786: float
    level_0_618: float
    level_0_500: float
    level_0_382: float
    level_0_236: float
    level_0_000: float
    is_active: int
    parent_grid_id: Optional[str] = None

class FvgEvent(BaseModel):
    fvg_id: str
    timeframe: str
    direction: str
    ts_candle1: datetime
    ts_candle3: datetime
    gap_top: float
    gap_bottom: float
    gap_size: float
    gap_size_pct: float
    is_extreme: int
    is_mitigated: int
    ts_mitigated: Optional[datetime] = None
    parent_fvg_id: Optional[str] = None

class PriceState(BaseModel):
    mid: float
    bid: float
    ask: float
    timestamp: datetime
