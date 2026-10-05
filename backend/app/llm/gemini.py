import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator

import httpx

from app.llm.base import ChatMessage, LLMBusyError, LLMProvider, LLMUnavailableError

log = logging.getLogger(__name__)
BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, *, client: httpx.AsyncClient | None = None,
                 max_retries: int = 3, base_delay: float = 1.0) -> None:
        self.api_key, self.model = api_key, model
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10))
        self.max_retries, self.base_delay = max_retries, base_delay

    async def stream_chat(self, messages: list[ChatMessage], *, max_tokens: int) -> AsyncIterator[str]:
        system = "\n".join(m.content for m in messages if m.role == "system")
        body: dict[str, object] = {
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                for m in messages if m.role != "system"
            ],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{BASE}/{self.model}:streamGenerateContent?alt=sse"
        for attempt in range(self.max_retries + 1):
            try:
                # The key goes in a header (never the URL) so it can't leak into logs.
                async with self.client.stream("POST", url, json=body, headers={"x-goog-api-key": self.api_key}) as r:
                    if r.status_code in (429, 503):
                        if attempt == self.max_retries:
                            raise LLMBusyError(f"Gemini {r.status_code} after {attempt + 1} attempts")
                        # Exponential backoff + jitter. Only retried before any text was sent to the user.
                        await asyncio.sleep(self.base_delay * 2**attempt + random.random() * 0.3)
                        continue
                    if r.status_code != 200:
                        await r.aread()
                        log.error("Gemini error %s: %s", r.status_code, r.text[:300])
                        raise LLMUnavailableError(f"Gemini returned {r.status_code}")
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        for cand in json.loads(line[5:]).get("candidates", []):
                            for part in cand.get("content", {}).get("parts", []):
                                if text := part.get("text"):
                                    yield text
                    return
            except httpx.TransportError as exc:
                raise LLMUnavailableError(f"Gemini network error: {type(exc).__name__}") from exc
