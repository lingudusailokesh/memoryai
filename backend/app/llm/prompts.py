SYSTEM_PROMPT = "You are MemoryAI, a helpful, concise assistant."
TITLE_PROMPT = (
    "Write a title of at most 6 words for a conversation that starts with the user message below. "
    "Reply with the title only, no quotes."
)
EXTRACT_PROMPT = (
    "You extract long-term memories about the USER from one conversation exchange. "
    "Reply with ONLY a JSON array (no prose, no code fences) of at most 5 objects: "
    '{"content": "<one short third-person fact, e.g. User is learning Python>", '
    '"category": "<preference|skill|goal|personal|project|other>", "importance": <number 0 to 1>}. '
    "Rules: keep only facts the USER stated about themselves that stay useful in future conversations; "
    "ignore the assistant's own text, questions, small talk and one-off tasks; never include passwords, API keys, "
    "ID numbers, card numbers or other secrets; if nothing is worth remembering reply with []."
)
DEDUPE_PROMPT = (
    "You compare NEW memories about a user with EXISTING ones. For each numbered pair decide: "
    '"same" (the same fact, possibly reworded or more detailed), "different" (unrelated or compatible facts), or '
    '"conflicting" (the new one contradicts or replaces the existing one, e.g. the user switched or changed their mind). '
    'Reply with ONLY a JSON array like [{"id": 1, "decision": "same"}], one object per pair, no prose.'
)
