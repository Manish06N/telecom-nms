"""Live outage feed. Connect with a normal access token as ?token=."""

import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.deps import get_current_user
from app.core.realtime import hub
from app.db.session import SessionLocal
from app.domain.enums import Permission
from app.domain.errors import AppError
from app.domain.permissions import role_has

router = APIRouter()


@router.websocket("/ws/outages")
async def outages(websocket: WebSocket, token: str = Query(...)):
    await websocket.accept()
    db = SessionLocal()
    try:
        user = get_current_user(token=token, db=db)
        if not role_has(user.role, Permission.OUTAGE_READ):
            raise AppError("You cannot watch outages", 403, "forbidden")
    except AppError as exc:
        await websocket.send_json({"error": exc.detail})
        await websocket.close(code=1008)
        db.close()
        return
    finally:
        db.close()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    hub.register(loop, queue)
    await websocket.send_json({"event": "connected"})
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        return
    finally:
        hub.unregister(loop, queue)
