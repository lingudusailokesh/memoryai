from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryVersionItem:
    content: str
    reason: str
    created_at: str


@dataclass(frozen=True)
class MemoryItem:
    id: str
    text: str
    score: float | None = None
    created_at: str | None = None
    updated_at: str | None = None
    category: str | None = None
    importance: float | None = None
    status: str | None = None
    superseded_by: str | None = None
    supersedes: str | None = None


class MemoryProvider(ABC):
    """What the chat service needs from a memory system. Mem0 and (Stage 7) our own implementation plug in here.

    Every call is scoped by user_id: a provider must never return one user's memories to another.
    Methods that take a memory_id also take user_id and must treat someone else's memory as nonexistent.
    """

    @abstractmethod
    async def search(self, user_id: str, query: str, *, top_k: int) -> list[MemoryItem]:
        """Memories relevant to `query`, best first."""

    @abstractmethod
    async def add_exchange(self, user_id: str, user_text: str, assistant_text: str, *, source: str | None = None) -> None:
        """Extract and store memories from one user/assistant exchange (one batch, not per message).

        `source` is the conversation id, for providers that record where a memory came from."""

    @abstractmethod
    async def list_all(self, user_id: str, *, limit: int) -> Sequence[MemoryItem]:
        """The user's memories, newest first."""

    @abstractmethod
    async def get(self, user_id: str, memory_id: str) -> MemoryItem | None: ...

    @abstractmethod
    async def update(self, user_id: str, memory_id: str, text: str) -> MemoryItem | None:
        """Replace a memory's text. None if it doesn't exist or isn't this user's."""

    @abstractmethod
    async def delete(self, user_id: str, memory_id: str) -> bool: ...

    @abstractmethod
    async def delete_all(self, user_id: str) -> int:
        """Delete every memory of this user; returns how many."""

    # ---- optional capabilities (only the custom provider has an inbox, superseded memories and history) ----
    async def list_pending(self, user_id: str, *, limit: int) -> Sequence[MemoryItem]:
        return []

    async def list_superseded(self, user_id: str, *, limit: int) -> Sequence[MemoryItem]:
        return []

    async def approve(self, user_id: str, memory_id: str) -> MemoryItem | None:
        return None

    async def reject(self, user_id: str, memory_id: str) -> bool:
        return False

    async def restore(self, user_id: str, memory_id: str) -> MemoryItem | None:
        return None

    async def versions(self, user_id: str, memory_id: str) -> Sequence[MemoryVersionItem] | None:
        """Newest first; None if the memory doesn't exist / isn't this user's."""
        return None
