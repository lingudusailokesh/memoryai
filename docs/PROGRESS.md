# Progress
## Stage 1 (approved)
FastAPI + /api/health, React/Vite/TS/Tailwind, tokens, light/dark theme, sidebar/header layout, mock Dashboard, static Chat, placeholders.
Limitations: not yet run or tested by the author; no Docker; no Vitest; header avatar menu/notifications missing; Dashboard has stat cards + one chart only.

## Stage 2 (approved)
Postgres+pgvector via Docker Compose, SQLAlchemy 2 async, Alembic migration 0001, tables users/conversations/messages, repositories with built-in user isolation, 7 tests.
Decisions: see docs/decisions.md items 5-11. Bug found and fixed: message ordering ties.
Limitations: migration not yet run against real Postgres by the author; no API routes use the DB yet (Stage 3/4); no `GET /api/ready` DB check yet; no pgvector extension yet.

## Stage 3 (approved)
Register/login/refresh/logout, `GET /api/me`, argon2 hashing, JWT access + rotating hashed refresh tokens (migration 0002), `get_current_user` dependency, React auth context, login/register pages, protected routes, logout button. 18 backend tests pass (11 new auth/isolation); `tsc` passes.
Limitations: no rate limiting or lockout (Stage 10); no refresh-token reuse detection (a replayed old token is rejected but doesn't revoke the user's other sessions); no email verification or password reset; `COOKIE_SECURE=true` needed in production; no frontend component tests yet; migration 0002 not yet run on real Postgres by the author.

## Stage 4 (approved)
Providers (Fake, Gemini, Ollama), chat service, SSE streaming, stop, retry/regenerate, auto titles, conversation PATCH/DELETE/messages routes, chat UI (markdown), conversations page. 30 backend tests pass; `tsc` passes.
Gemini free-tier limits (checked Oct 2026, sources disagree and Google no longer prints a per-model table): roughly 10-15 requests/min and a few hundred to ~1,000+ requests/day for Flash / Flash-Lite, per project, reset at midnight Pacific; free-tier content may be used to improve Google's models. Check the exact numbers for your key in AI Studio.
Limitations: Gemini and Ollama code is tested with mocked HTTP only (never called live by the author); no code highlighting yet; stopped/failed partial replies are saved without an "interrupted" marker; no per-user budget or throttle (Stage 10); no conversation rename UI (API exists); no Vitest tests.

## Stage 5 (approved)
MemoryProvider (Fake + Mem0 adapter), memory recall injected into the system prompt, background memory writes, per-conversation switch (create/PATCH, UI toggle, server-side enforcement), `messages.memories_used`, `GET /api/messages/{id}/memories-used`, "Used N memories" chip. 40 backend tests pass; `tsc` passes.
Limitations: **Mem0 itself has never been run end to end by the author** (tests use a stub client and check the config it would get); pgvector extension/migration 0003 and Mem0's own tables are untested on real Postgres; Mem0's sync client is called from threads and is untested under load; Mem0's own LLM calls are not rate-limited by our code; memories are not yet listable/editable/deletable (Stage 6); no 'memory used' for old messages created before this stage; frontend untested by Vitest.

## Stage 6 (approved)
Memories page (list, debounced search, inline edit, delete with confirmation, "Delete all" with type-DELETE), `GET/PATCH/DELETE /api/memories`, `POST /api/memories/delete-all`, ownership-checked provider methods, scrubbing of deleted memories from "used" snapshots. 47 backend tests pass; `tsc` passes.
Limitations: Mem0's get/update/delete/get_all are exercised only through a stub (never run live); snapshot scrubbing loads all of a user's assistant messages (fine now, needs a SQL JSON query at scale); no pagination beyond 100; the edit isn't re-embedded/verified live with Mem0; no frontend component tests; no manual "add a memory" (planned with Stage 7's custom memory work).

### Stage 6 verification note
Reported: /api/memories missing from /docs. The delivered Stage 6 code registers all four routes (checked over real HTTP: OpenAPI lists them, unauthenticated calls return 401, not 404). Added `tests/test_memories_routes.py` (route registration for the memories endpoints and all earlier routes, 401 without a token, end-to-end ownership). Most likely cause on the reporting machine: an old backend process still serving the Stage 5 code.

## Stage 7 (approved)
`MEMORY_PROVIDER=custom`: LLM extraction (1 call/exchange) -> local embeddings -> Postgres/pgvector (`memories`, HNSW cosine, migration 0004) -> gated, re-ranked retrieval; edit re-embeds; category/importance shown on the Memories page. 95 backend tests pass on SQLite; the 3 real-Postgres tests also pass (`TEST_POSTGRES_URL`, pgvector 0.6.0 on Postgres 16). Migrations 0001-0004 were run on that real Postgres.
Limitations: **real embeddings (fastembed) and real extraction (Gemini/Ollama) have never been run by the author** (no model-download access here); the similarity threshold 0.45 is a guess until Stage 9; the enforced sensitive-data guard is Stage 8, so with a real LLM a secret the user types could be stored; only exact duplicates are skipped; no manual "add memory" yet; the Memories page has no category filter/sort/pagination yet; Mem0 vs custom data are separate.

## Forgot password (approved)
`POST /api/auth/forgot-password`, `POST /api/auth/reset-password`, migration 0005, console/SMTP email senders, `/forgot-password` and `/reset-password` pages, "Forgot password?" link. 107 backend tests pass (12 new); `tsc` passes. Checked over real HTTP on real Postgres with the console sender: request, reset, reuse rejected (400), old password 401, new password 200.
Limitations: the SMTP sender is tested with a mock only (never sent a real email); no per-IP rate limiting (Stage 10); no email verification; no change-password-while-logged-in yet (Stage 10).

## Stage 8 (awaiting approval)
Importance heuristics, two-tier de-duplication, conflict resolution (supersede + restore), version history, `auto`/`ask` modes with a review inbox, sensitive-data guard, Memories page tabs (Memories / Suggested / Replaced), history view, mode selector. Migration 0006 (users.memory_mode, memories.superseded_by / supersedes_id, memory_versions) ran up/down/up on real Postgres 16 and on SQLite. 145 backend tests on SQLite pass; with `TEST_POSTGRES_URL` all 158 pass, including a conflict -> restore -> inbox flow on real pgvector. `tsc` passes.
Limitations: the similarity bands (0.92 / 0.65) and the fake "same/different/conflicting" heuristics are stand-ins: **real LLM decisions and real embeddings have never been run by the author**, so the bands need calibration (Stage 9); the guard is a pattern list; chat messages themselves are not scanned; one nearest neighbour per candidate (a candidate that conflicts with a second, less similar memory is not noticed); no manual "add memory"; no pinning UI; the frontend has no automated tests; Mem0 has no inbox/history (by design).

## Stages 9-12 (implemented; verification pending local dependency installation)
Real per-user dashboard/analytics APIs, persisted usage/retrieval events, focus suggestion, global search, settings/privacy export/delete-account, process-local rate limit and daily budget, Docker services, GitHub Actions, local seed/evaluation scripts, README/interview notes, and a narrow LangGraph study-plan endpoint. The dashboard and settings now call APIs instead of displaying mock placeholders.

Limitations: this archive has no Python interpreter, virtual environment, or `node_modules`, so the final test/type/build pass could not be run here. The evaluation harness intentionally contains a reproducible data set rather than fabricated benchmark numbers. Redis, deployment credentials, production CSP, and a background worker are documented next-scale upgrades, not included as pretend production infrastructure.
