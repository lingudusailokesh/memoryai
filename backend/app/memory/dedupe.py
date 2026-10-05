import json
import logging
import re
from typing import Literal

from app.llm.base import ChatMessage, LLMProvider
from app.llm.prompts import DEDUPE_PROMPT

log = logging.getLogger(__name__)
Decision = Literal["same", "different", "conflicting"]
_VALID = {"same", "different", "conflicting"}


def parse_decisions(raw: str, count: int) -> list[Decision]:
    """Never raises. Anything missing or unusable becomes "different": the safe default is to keep both memories."""
    out: list[Decision] = ["different"] * count
    found = re.search(r"\[.*\]", raw, re.S)
    try:
        data = json.loads(found.group(0)) if found else []
    except json.JSONDecodeError:
        return out
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), int) and 1 <= item["id"] <= count:
            decision = str(item.get("decision", "")).lower()
            if decision in _VALID:
                out[item["id"] - 1] = decision  # type: ignore[call-overload]
    return out


async def decide_pairs(llm: LLMProvider, pairs: list[tuple[str, str]]) -> list[Decision]:
    """ONE LLM call for every mid-similarity pair of an exchange. pairs = [(existing, new), ...]."""
    if not pairs:
        return []
    body = "\n".join(f"{i}. EXISTING: {old} | NEW: {new}" for i, (old, new) in enumerate(pairs, 1))
    try:
        return parse_decisions(await llm.complete([ChatMessage("system", DEDUPE_PROMPT), ChatMessage("user", body)], max_tokens=300),
                               len(pairs))
    except Exception:
        log.exception("duplicate check failed; keeping both memories")
        return ["different"] * len(pairs)
