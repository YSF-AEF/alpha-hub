from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..common.auth import check_ws_bearer
from ..common.time_util import utc_now_iso
from ..common.trace import new_trace_id, new_id
from ..common.errors import ApiError
from ..events.models import EventEnvelope
from ..models import (
    WsUserMessage,
    WsCancel,
    WsAssistantStatus,
    WsAssistantDelta,
    WsAssistantDone,
    Usage,
    CapabilityWarning,
)

router = APIRouter()


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket, conversation_id: Optional[str] = None):
    # Auth (reject before accept)
    auth = websocket.headers.get('authorization')
    try:
        check_ws_bearer(auth)
    except ApiError:
        await websocket.close(code=4401, reason='UNAUTHORIZED')
        return

    await websocket.accept()

    current_task: Optional[asyncio.Task] = None
    current_cancel: Optional[asyncio.Event] = None
    current_trace_id: Optional[str] = None

    async def send_done(
        *,
        trace_id: str,
        reason: str,
        message_id: Optional[str] = None,
        usage: Optional[dict] = None,
        capability_warnings: Optional[list[dict]] = None,
        error: Optional[dict] = None,
    ) -> None:
        done = WsAssistantDone(
            trace_id=trace_id,
            reason=reason,  # type: ignore[arg-type]
            message_id=message_id,
            usage=Usage(**(usage or {})),
            capability_warnings=[CapabilityWarning(**w) for w in (capability_warnings or [])],
            error=error,
        )
        await websocket.send_json(done.model_dump())

    async def send_status(trace_id: str, stage: str, detail: Optional[str] = None, progress: Optional[float] = None) -> None:
        msg = WsAssistantStatus(trace_id=trace_id, stage=stage, detail=detail, progress=progress)
        await websocket.send_json(msg.model_dump())

    async def send_delta(trace_id: str, delta: str) -> None:
        msg = WsAssistantDelta(trace_id=trace_id, delta=delta)
        await websocket.send_json(msg.model_dump())

    def resolve_conversation_id(msg_conversation_id: Optional[str]) -> Optional[str]:
        return msg_conversation_id or conversation_id

    def publish_received(*, trace_id: str, conversation_id: str, message_id: str, idempotency_key: Optional[str]) -> None:
        bus = websocket.app.state.bus
        env = EventEnvelope(
            event_id=new_id(),
            trace_id=trace_id,
            occurred_at_utc=utc_now_iso(),
            producer="core.gateway",
            type="message.received",
            version=1,
            privacy="normal",
            notify_policy="none",
            payload={"conversation_id": conversation_id, "message_id": message_id},
            idempotency_key=idempotency_key,
        )
        bus.publish("alpha.message.received", env)

    async def start_turn(msg: WsUserMessage) -> None:
        nonlocal current_task, current_cancel, current_trace_id

        if current_task and not current_task.done():
            await send_done(
                trace_id=current_trace_id or new_trace_id(),
                reason="error",
                error={"code": "CONFLICT", "message": "turn already running"},
            )
            return

        cid = resolve_conversation_id(msg.conversation_id)
        if not cid:
            await send_done(
                trace_id=msg.trace_id or new_trace_id(),
                reason="error",
                error={"code": "INVALID_ARGUMENT", "message": "conversation_id is required"},
            )
            return

        trace_id = msg.trace_id or new_trace_id()
        current_trace_id = trace_id

        user_message_id = new_id()
        publish_received(trace_id=trace_id, conversation_id=cid, message_id=user_message_id, idempotency_key=msg.client_request_id)

        current_cancel = asyncio.Event()

        async def _on_status(stage: str) -> None:
            await send_status(trace_id, stage)

        async def _on_delta(delta: str) -> None:
            await send_delta(trace_id, delta)

        orch = websocket.app.state.orchestrator
        attachments = [a.model_dump() for a in msg.attachments]  # [{'id': ...}]
        current_task = asyncio.create_task(
            orch.run_turn(
                conversation_id=cid,
                content_text=msg.content_text,
                attachments=attachments,
                on_status=_on_status,
                on_delta=_on_delta,
                cancel_event=current_cancel,
                trace_id=trace_id,
                user_message_id=user_message_id,
                client_request_id=msg.client_request_id,
            )
        )

    async def handle_cancel(msg: WsCancel) -> None:
        nonlocal current_cancel, current_trace_id

        if not current_task or current_task.done() or not current_cancel:
            await send_done(
                trace_id=msg.trace_id,
                reason="error",
                error={"code": "NOT_FOUND", "message": "no running turn"},
            )
            return

        if current_trace_id and msg.trace_id != current_trace_id:
            await send_done(
                trace_id=msg.trace_id,
                reason="error",
                error={"code": "NOT_FOUND", "message": "trace_id not running"},
            )
            return

        current_cancel.set()
        # The done frame will be emitted when the running task completes.

    async def finish_turn() -> None:
        nonlocal current_task, current_cancel, current_trace_id
        if not current_task:
            return
        result = await current_task
        await send_done(
            trace_id=result.trace_id,
            reason=result.reason,
            message_id=result.assistant_message.message_id if result.assistant_message else None,
            usage=result.usage,
            capability_warnings=result.capability_warnings,
            error=result.error,
        )
        current_task = None
        current_cancel = None
        current_trace_id = None

    async def handle_raw(raw_text: str) -> None:
        # tolerate invalid JSON and keep connection open
        try:
            obj = json.loads(raw_text)
        except Exception:
            await send_done(
                trace_id=new_trace_id(),
                reason="error",
                error={"code": "INVALID_ARGUMENT", "message": "invalid JSON"},
            )
            return

        if not isinstance(obj, dict):
            await send_done(
                trace_id=new_trace_id(),
                reason="error",
                error={"code": "INVALID_ARGUMENT", "message": "message must be a JSON object"},
            )
            return

        t = obj.get("type")
        try:
            if t == "user_message":
                msg = WsUserMessage.model_validate(obj)
                await start_turn(msg)
            elif t == "cancel":
                msg = WsCancel.model_validate(obj)
                await handle_cancel(msg)
            else:
                await send_done(
                    trace_id=obj.get("trace_id") or new_trace_id(),
                    reason="error",
                    error={"code": "INVALID_ARGUMENT", "message": f"unknown message type: {t!r}"},
                )
        except Exception as e:
            await send_done(
                trace_id=obj.get("trace_id") or new_trace_id(),
                reason="error",
                error={"code": "INVALID_ARGUMENT", "message": str(e)},
            )

    # Main loop: ensure we never call websocket.receive_* concurrently
    recv_task: Optional[asyncio.Task] = None
    turn_task: Optional[asyncio.Task] = None

    try:
        while True:
            if recv_task is None:
                recv_task = asyncio.create_task(websocket.receive_text())
            if current_task and turn_task is None:
                turn_task = asyncio.create_task(finish_turn())

            done, _pending = await asyncio.wait(
                [t for t in [recv_task, turn_task] if t is not None],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if recv_task in done:
                raw = await recv_task
                recv_task = None
                await handle_raw(raw)

            if turn_task in done:
                await turn_task
                turn_task = None

    except WebSocketDisconnect:
        if current_cancel:
            current_cancel.set()
        if current_task:
            try:
                await current_task
            except Exception:
                pass
    finally:
        for t in [recv_task, turn_task]:
            if t and not t.done():
                t.cancel()
