from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional

from ..common.time_util import utc_now_iso

Status = Literal["up", "degraded", "down"]
NotifyPolicy = Literal["explicit", "implicit_light", "none"]


@dataclass
class CapabilityState:
    name: str
    status: Status
    notify_policy_default: NotifyPolicy
    enabled: bool
    mode: str
    last_changed_at_utc: str


class CapabilityRegistry:
    """Capability status registry for client UX & graceful degradation."""

    def __init__(self) -> None:
        self._items: Dict[str, CapabilityState] = {}

    def set(
        self,
        *,
        name: str,
        status: Status,
        enabled: bool,
        mode: str,
        notify_policy_default: NotifyPolicy = "explicit",
        last_changed_at_utc: Optional[str] = None,
    ) -> None:
        self._items[name] = CapabilityState(
            name=name,
            status=status,
            notify_policy_default=notify_policy_default,
            enabled=enabled,
            mode=mode,
            last_changed_at_utc=last_changed_at_utc or utc_now_iso(),
        )

    def snapshot(self) -> list[CapabilityState]:
        return list(self._items.values())

    def get(self, name: str) -> CapabilityState:
        return self._items[name]
