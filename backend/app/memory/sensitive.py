"""Sensitive-data guard: memories must never hold secrets or identity numbers.

Defence in depth, not a promise of perfection: the extraction prompt already asks the model to skip these, this
code enforces it on whatever comes back (and on manual edits). It errs on the side of dropping a memory.
"""
import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("an API key or token", re.compile(
        r"\b(sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|xox[abprs]-[A-Za-z0-9-]{10,})")),
    ("a login token", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("a password or PIN", re.compile(
        r"\b(password|passcode|passphrase|pin|cvv|secret|api[ _-]?key|access[ _-]?token|auth[ _-]?token|private[ _-]?key)\b"
        r"\s*(?:is|are|=|:)\s*\S+", re.I)),
    ("a government ID number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b|\b[A-Z]{5}\d{4}[A-Z]\b")),
]
_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){13,19}(?!\d)")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def check_sensitive(text: str) -> str | None:
    """A short reason ("a password or PIN") if the text looks sensitive, else None."""
    for reason, pattern in _PATTERNS:
        if pattern.search(text):
            return reason
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return "a card number"
    return None
