import asyncio
from collections.abc import AsyncIterator

from app.llm.base import ChatMessage, LLMBusyError, LLMError, LLMProvider, LLMUnavailableError
import json
import re

from app.llm.prompts import DEDUPE_PROMPT, EXTRACT_PROMPT, TITLE_PROMPT
from app.memory.fake import _tokens


class FakeLLMProvider(LLMProvider):
    """Deterministic, offline. Replies are echoes, clearly labelled as fake.

    Test/manual hooks: put [[busy]] or [[fail]] in a message to trigger those errors.
    """

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.fail_next: LLMError | None = None  # raised once on the next call (for tests)
        self.calls = 0
        self.chat_calls: list[list[ChatMessage]] = []  # non-title requests, for tests

    async def stream_chat(self, messages: list[ChatMessage], *, max_tokens: int) -> AsyncIterator[str]:
        self.calls += 1
        if self.fail_next is not None:
            err, self.fail_next = self.fail_next, None
            raise err
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if messages and messages[0].content == TITLE_PROMPT:
            yield " ".join(last.split()[:5])
            return
        if messages and messages[0].content == EXTRACT_PROMPT:  # offline stand-in for memory extraction
            text = last.removeprefix("User message:\n").split("\n\nAssistant reply", 1)[0]
            facts = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.startswith("I ")]
            yield json.dumps([{"content": f, "category": "other", "importance": 0.5} for f in facts])
            return
        if messages and messages[0].content == DEDUPE_PROMPT:  # offline stand-in for the same/different/conflicting call
            out = []
            for line in last.splitlines():
                m = re.match(r"(\d+)\.\s*EXISTING:\s*(.*?)\s*\|\s*NEW:\s*(.*)$", line)
                if not m:
                    continue
                old, new = _tokens(m.group(2)), _tokens(m.group(3))
                if re.search(r"no longer|switched|instead|now prefer|moved to|anymore", m.group(3).lower()):
                    decision = "conflicting"
                elif old and new and len(old & new) / len(old | new) >= 0.5:
                    decision = "same"
                else:
                    decision = "different"
                out.append({"id": int(m.group(1)), "decision": decision})
            yield json.dumps(out)
            return
        self.chat_calls.append(messages)
        if "[[busy]]" in last:
            raise LLMBusyError("fake: busy")
        if "[[fail]]" in last:
            raise LLMUnavailableError("fake: unavailable")
        for word in f"[Fake AI] You said: {last}".split(" "):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield word + " "
