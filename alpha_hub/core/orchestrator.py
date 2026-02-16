from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable, Any

from ..capabilities.interfaces import ChatMessage, LlmProvider
from ..capabilities.mock_llm import MockLlmProvider
from ..common.time_util import utc_now_iso
from ..common.trace import new_trace_id, new_id
from ..events.bus import InProcessEventBus
from ..events.models import EventEnvelope
from ..storage.db import SqliteStore, MessageRow


@dataclass
class TurnResult:
    trace_id: str
    user_message: MessageRow
    assistant_message: Optional[MessageRow]
    reason: str
    usage: dict[str, int]
    capability_warnings: list[dict[str, str]]
    error: Optional[dict[str, Any]] = None


class Orchestrator:
    """Orchestrator: user message -> context -> LLM -> stream -> store -> events."""

    def __init__(
        self,
        *,
        store: SqliteStore,
        bus: InProcessEventBus,
        llm: Optional[LlmProvider] = None,
        context_limit: int = 30,
        system_prompt: str = "You are a helpful assistant.",
    ) -> None:
        self.store = store
        self.bus = bus
        self.llm: LlmProvider = llm or MockLlmProvider()
        self.context_limit = max(1, int(context_limit))
        self.system_prompt = system_prompt

    def _publish(
        self,
        *,
        event_type: str,
        trace_id: str,
        payload: dict[str, Any],
        producer: str = "core.orchestrator",
        privacy: str = "normal",
        notify_policy: str = "none",
        version: int = 1,
        idempotency_key: Optional[str] = None,
    ) -> None:
        env = EventEnvelope(
            event_id=new_id(),
            trace_id=trace_id,
            occurred_at_utc=utc_now_iso(),
            producer=producer,
            type=event_type,
            version=version,
            privacy=privacy,  # type: ignore[arg-type]
            notify_policy=notify_policy,  # type: ignore[arg-type]
            payload=payload,
            idempotency_key=idempotency_key,
        )
        topic = f"alpha.{event_type}"
        self.bus.publish(topic, env)

    async def run_turn(
        self,
        *,
        conversation_id: str,
        content_text: str,
        attachments: list[dict],
        on_status: Callable[[str], Awaitable[None]],
        on_delta: Callable[[str], Awaitable[None]],
        cancel_event: asyncio.Event,
        trace_id: Optional[str] = None,
        user_message_id: Optional[str] = None,
        client_request_id: Optional[str] = None,
    ) -> TurnResult:
        trace_id = trace_id or new_trace_id()
        user_message_id = user_message_id or new_id()

        # 1) Store user message
        user_row = self.store.create_message(
            message_id=user_message_id,
            conversation_id=conversation_id,
            role="user",
            content_text=content_text,
            attachments=attachments,
            client_request_id=client_request_id,
        )
        self._publish(
            event_type="message.stored",
            trace_id=trace_id,
            payload={"conversation_id": conversation_id, "message_id": user_row.message_id, "role": "user"},
            notify_policy="none",
        )

        # 2) Build context
        history = self.store.list_messages(conversation_id, limit=self.context_limit)
        ctx: list[ChatMessage] = [ChatMessage(role="system", content_text=self.system_prompt)]
        for row in history:
            # history includes the just-stored user message; avoid duplicating it
            if row.message_id == user_row.message_id:
                continue
            if row.role in ("user", "assistant"):
                ctx.append(ChatMessage(role=row.role, content_text=row.content_text))
        ctx.append(ChatMessage(role="user", content_text=content_text))

        # 3) Run LLM streaming
        await on_status("queued")
        if cancel_event.is_set():
            return TurnResult(
                trace_id=trace_id,
                user_message=user_row,
                assistant_message=None,
                reason="cancelled",
                usage={"input_tokens": 0, "output_tokens": 0},
                capability_warnings=[],
            )

        await on_status("thinking")

        out_text_parts: list[str] = []
        try:
            await on_status("streaming")
            async for delta in self.llm.astream(messages=ctx, cancel=cancel_event):
                if cancel_event.is_set():
                    break
                out_text_parts.append(delta)
                await on_delta(delta)
        except Exception as e:
            return TurnResult(
                trace_id=trace_id,
                user_message=user_row,
                assistant_message=None,
                reason="error",
                usage={"input_tokens": 0, "output_tokens": 0},
                capability_warnings=[{"name": "llm", "status": "down", "notify": "explicit"}],
                error={"code": "UNAVAILABLE", "message": str(e)},
            )

        if cancel_event.is_set():
            return TurnResult(
                trace_id=trace_id,
                user_message=user_row,
                assistant_message=None,
                reason="cancelled",
                usage={"input_tokens": 0, "output_tokens": 0},
                capability_warnings=[],
            )

        out_text = "".join(out_text_parts)

        # 4) Store assistant message
        assistant_row = self.store.create_message(
            message_id=new_id(),
            conversation_id=conversation_id,
            role="assistant",
            content_text=out_text,
            attachments=[],
            client_request_id=None,
        )
        self._publish(
            event_type="message.stored",
            trace_id=trace_id,
            payload={"conversation_id": conversation_id, "message_id": assistant_row.message_id, "role": "assistant"},
            notify_policy="none",
        )

        # 5) Usage (best-effort; tokenizer not integrated yet)
        usage = {
            "input_tokens": max(0, len(content_text.split())),
            "output_tokens": max(0, len(out_text.split())),
        }

        return TurnResult(
            trace_id=trace_id,
            user_message=user_row,
            assistant_message=assistant_row,
            reason="completed",
            usage=usage,
            capability_warnings=[],
        )
