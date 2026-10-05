import json
import re
from dataclasses import dataclass, replace

from app.config import settings
from app.llm.base import ChatMessage, LLMProvider
from app.llm.prompts import EXTRACT_PROMPT

CATEGORIES = {"preference", "skill", "goal", "personal", "project", "other"}
MIN_WORDS, MAX_CHARS = 3, 300


@dataclass(frozen=True)
class Candidate:
    content: str
    category: str
    importance: float


def parse_candidates(raw: str) -> list[Candidate]:
    """Turn the model's reply into validated candidates. Never raises: unusable output means no memories."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        found = re.search(r"\[.*\]", text, re.S)  # tolerate prose around the array
        try:
            data = json.loads(found.group(0)) if found else []
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict):
        data = data.get("memories", [])
    if not isinstance(data, list):
        return []
    out: list[Candidate] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content", "")).split())
        if len(content.split()) < MIN_WORDS or len(content) > MAX_CHARS or content.lower() in seen:
            continue  # empty, trivial, too long, or repeated within this reply
        seen.add(content.lower())
        category = str(item.get("category", "other")).lower()
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5
        out.append(Candidate(content, category if category in CATEGORIES else "other", min(1.0, max(0.0, importance))))
        if len(out) == settings.memory_max_per_exchange:
            break
    return out


_MARKERS = re.compile(r"\b(always|never|must|every (?:day|week)|my goal|preparing for|deadline|allergic|prefers?)\b", re.I)


def refine_importance(c: Candidate) -> Candidate:
    """The LLM's 0..1 score plus simple, explainable nudges: goals/projects and strong wording matter more, "other" less."""
    score = c.importance
    if c.category in ("goal", "project"):
        score += 0.1
    if _MARKERS.search(c.content):
        score += 0.1
    if c.category == "other":
        score -= 0.05
    return replace(c, importance=round(min(1.0, max(0.0, score)), 3))


class MemoryExtractor:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def extract(self, user_text: str, assistant_text: str) -> list[Candidate]:
        """ONE LLM call per exchange (not per message). LLM errors propagate; the caller logs and moves on."""
        raw = await self.llm.complete(
            [ChatMessage("system", EXTRACT_PROMPT),
             ChatMessage("user", f"User message:\n{user_text[:2000]}\n\nAssistant reply (context only):\n{assistant_text[:1000]}")],
            max_tokens=500)
        return parse_candidates(raw)
