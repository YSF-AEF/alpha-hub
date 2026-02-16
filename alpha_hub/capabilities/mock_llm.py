from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .interfaces import ChatMessage, LlmProvider


class MockLlmProvider(LlmProvider):
    """Mock streaming LLM for WS streaming + cancel semantics.

    Intentionally: slow enough so cancel test can reliably trigger.
    """

    async def astream(self, messages: list[ChatMessage], cancel: asyncio.Event) -> AsyncIterator[str]:
        await asyncio.sleep(0.05)

        # Take the last user message as prompt.
        prompt = ""
        for m in reversed(messages):
            if m.role == "user":
                prompt = m.content_text
                break

        text = f"Echo: {prompt} " + ("." * 200)
        for ch in text:
            if cancel.is_set():
                return
            await asyncio.sleep(0.01)
            yield ch
