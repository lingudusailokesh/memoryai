from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class LLMError(Exception):
    """Base class. Messages here are for logs only; users get friendly text from the chat service."""


class LLMBusyError(LLMError):
    """Rate limited (429) even after retries."""


class LLMUnavailableError(LLMError):
    """Network failure, bad status, or an empty/blocked reply."""


class LLMProvider(ABC):
    """The only thing the rest of the app knows about an LLM vendor.

    (Embeddings join this interface in Stage 7, when something actually uses them.)
    """

    @abstractmethod
    def stream_chat(self, messages: list[ChatMessage], *, max_tokens: int) -> AsyncIterator[str]:
        """Yield text chunks as they arrive."""

    async def complete(self, messages: list[ChatMessage], *, max_tokens: int) -> str:
        return "".join([chunk async for chunk in self.stream_chat(messages, max_tokens=max_tokens)])
