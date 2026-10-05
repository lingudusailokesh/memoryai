# Memory system (custom provider, Stage 7)

Two interchangeable providers sit behind `MemoryProvider`: **Mem0** (Stage 5) and our **custom** pipeline (this stage).
Select with `MEMORY_PROVIDER=fake|mem0|custom`. They keep separate stores, so switching providers does not carry memories across.

## Pipeline
```
user message -> LLM reply (streamed) -> saved
   [retrieval, before the reply]  embed query -> pgvector top candidates -> similarity gate -> re-rank -> top_k -> prompt
   [write, after the reply, background]  1 LLM call: extract -> validate -> skip exact duplicates -> 1 embedding batch -> insert
```
Retrieval and writing both obey the per-conversation switch (read from the DB; the write re-checks it right before saving).
Turning memory on again does not extract from messages sent while it was off.

## Extraction (`memory/extraction.py`)
One LLM call per exchange, not per message. The model returns a JSON array of `{content, category, importance}`.
Validation: unusable output means no memories; items under 3 words, over 300 chars, or repeated are dropped; unknown categories become
`other`; importance is clamped to 0..1; at most 5 memories per exchange. The prompt tells the model not to keep secrets, but that is
a request, not a guarantee, so `memory/sensitive.py` enforces it on every candidate and on manual edits (see below).

## Storage (`memories` table)
`content, category, importance, pinned, status, embedding vector(384), embedding_model, source_conversation_id, created_at, updated_at`.
`embedding_model` is stored per row so a model change is detectable and memories can be re-embedded. The dimension (384, bge-small)
is fixed by the migration; a model with another dimension needs a new migration plus re-embedding.

**Index: HNSW with cosine ops.** HNSW needs no training data (works on an empty table and as it grows) and gives good recall at this size;
IVFFlat must be built after data exists and re-tuned as it grows. Cosine matches how these embeddings are trained.
Caveat: with a `user_id` filter an approximate index can return fewer than `k` rows for users with few memories among many.
At this scale Postgres usually prefers the `user_id` btree anyway; revisit (iterative scans, partitioning) if the table gets large.

## Relevance score (`memory/scoring.py`)
```
final = 0.70*similarity + 0.15*importance + 0.10*recency + 0.05*pinned        (weights in config)
recency = 0.5 ^ (age_days / 60)
```
Similarity is a **gate first** (`MEMORY_MIN_SIMILARITY`, default 0.45): importance, recency and pinned only re-rank memories that are already
relevant and can never pull in an irrelevant one. The best `top_k` (default 5) go to the prompt; the whole store is never sent.
The default threshold is a starting guess for bge-small and **must be calibrated** (Stage 9 evaluation will tune it).

## Embeddings
`EmbeddingProvider` (separate from the chat LLM; the vendor LLM is not involved). `fastembed` runs bge-small locally on CPU (ONNX, no PyTorch).
`FakeEmbedder` (default) is a hashed bag of words for offline use and tests; it is not semantic. A small in-process cache means the same text is
never embedded twice (repeated queries, retried writes).

## Failure behaviour
- Query embedding fails or search is slow (8s): the chat answers without memory.
- Extraction LLM fails, returns garbage, or embedding fails on write: nothing is stored, the error is logged, the chat is unaffected.
- A stopped or failed reply is not remembered.

## Lifecycle (Stage 8)
**Importance.** The LLM's 0..1 score plus explainable nudges (`refine_importance`): goals/projects +0.1, strong wording ("always", "never", "preparing for"...) +0.1, category "other" -0.05.

**De-duplication, two tiers** (thresholds are config, uncalibrated until Stage 9):
```
each new candidate -> nearest ACTIVE memory of the same user (pgvector)
  similarity >= 0.92          same fact: merge, no LLM call (keep higher importance)
  0.65 <= similarity < 0.92   ambiguous: ONE LLM call for all such pairs of the exchange -> same | different | conflicting
  similarity < 0.65           new fact
```
Cost per exchange: 1 extraction call, at most 1 decision call, 1 embedding batch. If the decision call fails or is unparseable the answer is
"different": we keep both rather than lose anything. "Same" with clearly fuller wording (>20% longer) replaces the text and keeps the old text in history.

**Conflicts.** "conflicting" means the user changed their mind ("I switched from Java to Python"). The new memory becomes active, the old one `superseded`
(kept, never retrieved, restorable). Restoring swaps them: the old one is active again and its replacement becomes the superseded one.

**Modes** (`users.memory_mode`): `auto` saves new memories; `ask` puts new facts in an inbox as `pending` (never retrieved) until approved.
In `ask` mode a duplicate adds nothing to ask about, an existing memory is never rewritten silently, and a conflicting suggestion remembers which memory it
would replace (`supersedes_id`) and only does so on approval.

**History** (`memory_versions`): the previous text is kept when a memory is edited, merged into, superseded or restored.
Deleting a memory removes its history with it (cascade) and its text from earlier "Used memories" lists.

**Sensitive-data guard** (`memory/sensitive.py`): drops candidates that look like private keys, API keys/tokens, login tokens, "password/PIN/secret is ...",
Luhn-valid card numbers, SSN, Aadhaar-shaped and PAN-shaped numbers; also refuses manual edits that contain them. It is a pattern list, not a guarantee:
it errs toward dropping, and it cannot recognise a secret that looks like an ordinary word. Messages in the chat itself are not scanned or blocked.

## Not yet
Optional manual "add a memory" button; pinning UI (the `pinned` column and score weight exist); category filter/sort/pagination on the Memories page;
calibration of every threshold against a labelled evaluation (Stage 9).
