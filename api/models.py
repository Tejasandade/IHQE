from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from datetime import datetime
from api.auth.database import Base

class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    signal_type = Column(String, index=True) # Strong Long, Moderate Long, Moderate Short, Strong Short, Path Scalp
    composite_score = Column(Float)
    metadata_json = Column(JSON) # JSON containing per-timeframe biases
