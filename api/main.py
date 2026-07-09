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

from api.routers import ohlcv, signals, cascade, live, backtest, sniper, intelligence
from api.auth.router import router as auth_router
from api.auth.database import engine, Base, SessionLocal
from api.auth.models import User
from api.auth.security import get_password_hash
from api.auth.middleware import get_current_user
from config.settings import ADMIN_EMAIL, ADMIN_PASSWORD
from fastapi import Depends
import asyncio
from ingestion.tiingo_client import start_tiingo_client

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
            
        # Check Materialized Views checkpoints on startup
        from database.clickhouse_client import ClickHouseClient
        import subprocess
        import os
        
        try:
            ch_client = ClickHouseClient()
            count_df = ch_client.query_df("SELECT count() as c FROM ihqe.simulation_monthly_checkpoints")
            if not count_df.empty and count_df.iloc[0]["c"] == 0:
                logging.info("Materialized views checkpoints are empty. Triggering precomputation in the background...")
                script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "precompute_monthly_checkpoints.py"))
                subprocess.Popen(["python", script_path])
        except Exception as e:
            logging.error(f"Failed to check or trigger materialized view precomputation: {e}")
            
    finally:
        db.close()
        
    # Start Tiingo background client
    asyncio.create_task(start_tiingo_client())

# Mount auth router (public)
app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])

@app.get("/api/health", tags=["System"])
def health_check():
    from database.clickhouse_client import ClickHouseClient
    from api.auth.database import engine as pg_engine
    from sqlalchemy import text
    from ingestion.tiingo_client import tiingo_status
    
    status = {
        "status": "ok",
        "clickhouse": "unknown",
        "postgresql": "unknown",
        "tiingo": tiingo_status
    }
    
    # Check ClickHouse
    try:
        ch = ClickHouseClient()
        ch.execute("SELECT 1")
        status["clickhouse"] = "ok"
    except Exception as e:
        status["clickhouse"] = f"error: {str(e)}"
        status["status"] = "degraded"
        
    # Check PostgreSQL
    try:
        with pg_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["postgresql"] = "ok"
    except Exception as e:
        status["postgresql"] = f"error: {str(e)}"
        status["status"] = "degraded"
        
    return status

# Mount protected routers
protected = [Depends(get_current_user)]
app.include_router(ohlcv.router, prefix="/api", tags=["OHLCV"], dependencies=protected)
app.include_router(signals.router, prefix="/api", tags=["Signals"], dependencies=protected)
app.include_router(cascade.router, prefix="/api", tags=["Cascade"], dependencies=protected)
app.include_router(sniper.router, prefix="/api/sniper", tags=["Sniper"])
app.include_router(intelligence.router, prefix="/api/intelligence", tags=["Intelligence"])
app.include_router(live.router, prefix="/api", tags=["Live"])
app.include_router(backtest.router, prefix="/api", tags=["Backtest"], dependencies=protected)
from api.routers import simulation
app.include_router(simulation.router, prefix="/api", tags=["Simulation"])

@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "3.0.0"}
