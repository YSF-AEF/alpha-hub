from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Protocol, Literal


@dataclass(frozen=True)
class ChatMessage:
    """A minimal chat message used by the kernel.

    We keep this small and stable; providers can map it to their own schemas.
    """

    role: Literal["system", "user", "assistant"]
    content_text: str


class LlmProvider(Protocol):
    """LLM interface (kernel depends on interface, not implementation)."""

    async def astream(self, messages: list[ChatMessage], cancel: asyncio.Event) -> AsyncIterator[str]:
        ...
