# MemoryAI
Multi-user AI assistant with real long-term memory (extract, store, retrieve, dedupe, resolve conflicts). Portfolio project for SDE interviews: everything must be explainable.

## Stack
React + Vite + TS (strict) + Tailwind + Recharts; FastAPI (Python 3.12); later: Postgres+pgvector, SQLAlchemy async, Alembic, LLM provider abstraction (Gemini free / Ollama ≤3B / Fake), fastembed (384 dims), LangGraph (last).

## Rules
Stage by stage; wait for "approved". Explain architectural decisions and log them in docs/decisions.md. Ask if ambiguity affects architecture. Debug root causes. No fake functionality unless labeled mock. No secrets in code. Keep it simple; small reviewable changes. Budget $0. Machine: 16 GB RAM, no GPU.

## Stages
1 Skeleton + UI shell (done) · 2 DB (done) · 3 Auth (done) · 4 LLM + chat (done) · 5 Mem0 (done) · 6 Memories page (done) · 7 Custom memory (done) · 8 Dedupe/conflicts (done) · 9 Analytics + eval (done) · 10 Limits/polish (done) · 11 Docker/CI/docs (done) · 12 LangGraph (done)

## Commands
Database: `docker compose up -d db` then `cd backend && alembic upgrade head`
LLM defaults to the offline fake; set `LLM_PROVIDER=gemini` + `GEMINI_API_KEY` for real replies.
Memory defaults to the offline fake; `MEMORY_PROVIDER=mem0` needs `pip install -r backend/requirements-mem0.txt` and a real LLM.
Custom memory: `MEMORY_PROVIDER=custom` (see docs/memory-system.md). Real-Postgres tests: set `TEST_POSTGRES_URL`.
Needs `JWT_SECRET` in backend/.env (see .env.example).
Backend: `cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && uvicorn app.main:app --reload` · test: `pytest`
Frontend: `cd frontend && npm install && npm run dev` · typecheck: `npm run typecheck`
Full stack: copy `.env.example` to both `.env` and `backend/.env`, set the same `JWT_SECRET`, then `docker compose up --build`. Seed: `make seed` (or `cd backend && python scripts/seed.py`).
