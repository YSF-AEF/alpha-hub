from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class EventEnvelope:
    """Event contract envelope (v0).

    Note:
    - Topic naming is handled by the event bus (e.g. alpha.message.received).
    - `type` should be the domain event name without the `alpha.` prefix (e.g. message.received).
    """

    event_id: str
    trace_id: str
    occurred_at_utc: str
    producer: str
    type: str
    version: int
    privacy: Literal["normal", "private_monitoring"]
    notify_policy: Literal["explicit", "implicit_light", "none"]
    payload: dict[str, Any]
    idempotency_key: Optional[str] = None
