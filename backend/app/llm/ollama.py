import json
from collections.abc import AsyncIterator

import httpx

from app.llm.base import ChatMessage, LLMProvider, LLMUnavailableError


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str, *, client: httpx.AsyncClient | None = None) -> None:
        self.base_url, self.model = base_url.rstrip("/"), model
        # Small local models on CPU can take a while to produce the first token.
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(300, connect=5))

    async def stream_chat(self, messages: list[ChatMessage], *, max_tokens: int) -> AsyncIterator[str]:
        body = {
            "model": self.model, "stream": True,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "options": {"num_predict": max_tokens},
        }
        try:
            async with self.client.stream("POST", f"{self.base_url}/api/chat", json=body) as r:
                if r.status_code != 200:
                    await r.aread()
                    raise LLMUnavailableError(f"Ollama returned {r.status_code}: {r.text[:200]}")
                async for line in r.aiter_lines():
                    if line.strip() and (text := json.loads(line).get("message", {}).get("content")):
                        yield text
        except httpx.TransportError as exc:
            raise LLMUnavailableError(f"Ollama not reachable at {self.base_url}") from exc
