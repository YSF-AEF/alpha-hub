from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator, Iterable, Optional

import httpx

from ..capabilities.interfaces import ChatMessage, LlmProvider


@dataclass(frozen=True)
class RemoteChatConfig:
    base_url: str
    api_key: Optional[str]
    model: str
    stream_path: str
    timeout_s: float = 30.0


def _iter_sse_payloads(lines: Iterable[str]) -> Iterable[str]:
    """Extract raw SSE payload strings from 'data: ...' lines.

    Why:
    - Many OpenAI-compatible servers send Server-Sent Events with:
      data: {json}
      data: [DONE]
    - There can also be keepalive blank lines.
    """
    for line in lines:
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                yield payload


def _extract_delta_text(payload_json: dict) -> str:
    """Extract the incremental delta text from a streamed chat completion chunk."""
    try:
        choices = payload_json.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or {}
        # OpenAI format
        txt = delta.get("content")
        if isinstance(txt, str):
            return txt
        # Some proxies might use 'text'
        txt2 = delta.get("text")
        if isinstance(txt2, str):
            return txt2
        return ""
    except Exception:
        return ""


class RemoteChatCompletionsProvider(LlmProvider):
    """OpenAI-compatible chat completions streaming provider.

    Contract:
    - astream(messages, cancel) yields incremental strings (tokens/chunks).
    """

    def __init__(self, cfg: RemoteChatConfig) -> None:
        self.cfg = cfg

    async def astream(self, messages: list[ChatMessage], cancel: asyncio.Event) -> AsyncIterator[str]:
        url = self.cfg.base_url.rstrip("/") + self.cfg.stream_path
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"

        payload = {
            "model": self.cfg.model,
            "stream": True,
            "messages": [{"role": m.role, "content": m.content_text} for m in messages],
        }

        timeout = httpx.Timeout(self.cfg.timeout_s)

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()

                async for line in resp.aiter_lines():
                    if cancel.is_set():
                        return
                    # SSE format: empty lines + 'data: ...'
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue

                    raw = line[len("data:"):].strip()
                    if raw == "[DONE]":
                        return

                    try:
                        chunk = json.loads(raw)
                    except Exception:
                        continue

                    delta = _extract_delta_text(chunk)
                    if delta:
                        yield delta
