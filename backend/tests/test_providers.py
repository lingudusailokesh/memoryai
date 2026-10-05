import httpx
import pytest

from app.llm.base import ChatMessage, LLMBusyError, LLMUnavailableError
from app.llm.gemini import GeminiProvider
from app.llm.ollama import OllamaProvider

MSGS = [ChatMessage("system", "be brief"), ChatMessage("user", "hi"), ChatMessage("assistant", "yo"), ChatMessage("user", "q")]
SSE = 'data: {"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}\n\ndata: {"candidates":[{"content":{"parts":[{"text":"lo"}]}}]}\n\n'


def gemini(handler, **kw) -> GeminiProvider:
    return GeminiProvider("SECRET-KEY", "m", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                          base_delay=0, **kw)


async def test_gemini_streams_and_maps_roles_and_hides_key():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers["x-goog-api-key"], req.read().decode()
        return httpx.Response(200, text=SSE)

    out = [c async for c in gemini(handler).stream_chat(MSGS, max_tokens=50)]
    assert out == ["Hel", "lo"]
    assert "SECRET-KEY" not in seen["url"] and seen["key"] == "SECRET-KEY"
    assert '"role":"model"' in seen["body"].replace(" ", "") and "systemInstruction" in seen["body"]


async def test_gemini_retries_429_then_succeeds_and_gives_up_as_busy():
    calls = {"n": 0}

    def flaky(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] < 3 else httpx.Response(200, text=SSE)

    assert "".join([c async for c in gemini(flaky).stream_chat(MSGS, max_tokens=5)]) == "Hello"
    assert calls["n"] == 3
    with pytest.raises(LLMBusyError):
        [c async for c in gemini(lambda r: httpx.Response(429), max_retries=2).stream_chat(MSGS, max_tokens=5)]
    with pytest.raises(LLMUnavailableError):
        [c async for c in gemini(lambda r: httpx.Response(500, text="boom")).stream_chat(MSGS, max_tokens=5)]


async def test_ollama_parses_ndjson_and_reports_unreachable():
    nd = '{"message":{"content":"a"}}\n{"message":{"content":"b"},"done":false}\n{"done":true}\n'
    ok = OllamaProvider("http://x", "m", client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=nd))))
    assert [c async for c in ok.stream_chat(MSGS, max_tokens=5)] == ["a", "b"]

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    bad = OllamaProvider("http://x", "m", client=httpx.AsyncClient(transport=httpx.MockTransport(down)))
    with pytest.raises(LLMUnavailableError):
        [c async for c in bad.stream_chat(MSGS, max_tokens=5)]
