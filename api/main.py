"""
IHQE v3 — FastAPI Application

Serves ClickHouse data to the React frontend.
All heavy computation (BOS detection, FVG scanning, cascade state)
is done by the Python engine and stored in ClickHouse.
FastAPI only reads from ClickHouse and formats for the frontend.
"""

import logging
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from api.routers import ohlcv, signals, cascade, live, backtest, sniper
from api.auth.router import router as auth_router
from api.auth.database import engine, Base, SessionLocal
from api.auth.models import User
from api.auth.security import get_password_hash
from api.auth.middleware import get_current_user
from config.settings import ADMIN_EMAIL, ADMIN_PASSWORD
from fastapi import Depends

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = FastAPI(
    title="IHQE v3 API",
    description="Interbank Harmonic Quantitative Engine — XAU/USD Trading Platform",
    version="3.0.0",
)

# CORS — allow React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create auth tables
Base.metadata.create_all(bind=engine)

@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if not admin:
            admin_user = User(
                email=ADMIN_EMAIL,
                password_hash=get_password_hash(ADMIN_PASSWORD),
                role="admin"
            )
            db.add(admin_user)
            db.commit()
            logging.info(f"Created default admin user: {ADMIN_EMAIL}")
    finally:
        db.close()

# Mount auth router (public)
app.include_router(auth_router.router, prefix="/api/auth", tags=["Auth"])

# Mount protected routers
protected = [Depends(get_current_user)]
app.include_router(ohlcv.router, prefix="/api", tags=["OHLCV"], dependencies=protected)
app.include_router(signals.router, prefix="/api", tags=["Signals"], dependencies=protected)
app.include_router(cascade.router, prefix="/api", tags=["Cascade"], dependencies=protected)
app.include_router(sniper.router, prefix="/api/sniper", tags=["Sniper"])
app.include_router(live.router, prefix="/api", tags=["Live"], dependencies=protected)
app.include_router(backtest.router, prefix="/api", tags=["Backtest"], dependencies=protected)


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "3.0.0"}
