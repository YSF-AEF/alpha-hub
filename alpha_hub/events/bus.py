from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, DefaultDict, List
from collections import defaultdict

from .models import EventEnvelope

Subscriber = Callable[[str, EventEnvelope], None]

@dataclass
class InProcessEventBus:
    """v0 事件总线：进程内发布/订阅。"""

    _subs: DefaultDict[str, List[Subscriber]] = None  # type: ignore

    def __post_init__(self) -> None:
        if self._subs is None:
            self._subs = defaultdict(list)

    def subscribe(self, topic: str, fn: Subscriber) -> None:
        self._subs[topic].append(fn)

    def publish(self, topic: str, env: EventEnvelope) -> None:
        for fn in self._subs.get(topic, []):
            fn(topic, env)
