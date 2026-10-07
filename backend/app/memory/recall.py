"""Recognize explicit profile questions, not arbitrary mentions of preferences."""
import re


_PREFERENCE_QUERY = re.compile(
    r"(?:what (?:do i (?:like|enjoy|prefer)|are my (?:preferences|interests|likes))"
    r"|(?:tell me|what do you (?:know|remember)) about my (?:preferences|interests|likes))",
    re.IGNORECASE,
)


def asks_for_preferences(query: str) -> bool:
    # Full match avoids treating topic-specific questions (e.g. 'what do I like about Java?')
    # as requests to inject unrelated preferences. No model call or user text execution.
    return _PREFERENCE_QUERY.fullmatch(" ".join(query.strip().rstrip("?!. ").split())) is not None
