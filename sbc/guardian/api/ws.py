"""WebSocket /ws: push `status` (1 Hz) dan `event` / `event_update` (real-time)."""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .auth import ws_authorized
from .status import build_status

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    if not ws_authorized(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    ctx = ws.app.state.ctx
    q = ctx.bus.subscribe_tagged(["event", "event_update"])
    try:
        await ws.send_json({"type": "status", "data": build_status(ctx)})
        next_status = time.monotonic() + 1.0
        while True:
            timeout = max(0.0, next_status - time.monotonic())
            try:
                topic, msg = await asyncio.wait_for(q.get(), timeout=timeout)
                await ws.send_json({"type": topic, "data": msg})
            except asyncio.TimeoutError:
                pass
            if time.monotonic() >= next_status:
                await ws.send_json({"type": "status", "data": build_status(ctx)})
                next_status = time.monotonic() + 1.0
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        log.exception("websocket error")
    finally:
        ctx.bus.unsubscribe_tagged(q)
