"""Small in-memory limiter for a single process; Redis is the production replacement."""
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta


class RateLimitError(Exception):
    pass


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[datetime]] = defaultdict(deque)

    def check(self, key: str, limit: int, window: timedelta) -> None:
        now = datetime.now(UTC)
        entries = self._events[key]
        while entries and entries[0] <= now - window:
            entries.popleft()
        if len(entries) >= limit:
            raise RateLimitError
        entries.append(now)


limiter = InMemoryRateLimiter()
