from fastapi import APIRouter
from engine.intelligence.mtf_engine import mtf_engine

router = APIRouter()

@router.get("/score")
def get_intelligence_score():
    """
    Returns the composite score and per-timeframe bias dict.
    We just run the engine synchronously to get the latest state.
    (In production, the engine runs asynchronously and caches this, but since it's fast ClickHouse queries, this works).
    """
    result = mtf_engine.run()
    return {
        "composite_score": result["composite_score"],
        "biases": result["biases"]
    }

@router.get("/conflicts")
def get_intelligence_conflicts():
    """
    Returns active Path Scalp flags.
    """
    result = mtf_engine.run()
    return {
        "path_scalp": result["path_scalp"]
    }
