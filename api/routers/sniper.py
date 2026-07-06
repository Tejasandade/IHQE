import asyncio
import json
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session
import jwt
from pydantic import ValidationError

from engine.sniper.core import sniper_engine
from api.auth.database import get_db
from api.auth.models import User
from api.auth.security import ALGORITHM
from config.settings import JWT_SECRET

router = APIRouter()

def get_current_user_query(token: str = Query(None), db: Session = Depends(get_db)):
    """
    Dependency to validate JWT from a query parameter.
    Standard EventSource in the browser does not support setting custom headers (like Authorization: Bearer).
    Therefore, we pass the token via query string specifically for this SSE endpoint.
    This is a known minor security tradeoff but standard practice for SSE endpoints.
    """
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    except (jwt.PyJWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/stream")
async def sniper_stream(user: User = Depends(get_current_user_query)):
    """
    SSE endpoint for Sniper Engine anomalies.
    """
    async def event_generator():
        # Subscribe to the sniper engine event stream
        queue = await sniper_engine.subscribe()
        try:
            while True:
                # Wait for an event
                event = await queue.get()
                # Yield the event as a Server-Sent Event formatted string
                yield {
                    "event": event.get("type", "message"),
                    "data": json.dumps(event)
                }
        except asyncio.CancelledError:
            # Client disconnected
            pass
        finally:
            sniper_engine.unsubscribe(queue)

    return EventSourceResponse(event_generator())
