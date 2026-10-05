from contextlib import asynccontextmanager

import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import agents, analytics, auth, conversations, health, me, memories, messages
from app.config import settings
from app.llm.factory import get_provider
from app.mailer.senders import get_email_sender
from app.memory.factory import get_memory_provider

@asynccontextmanager
async def lifespan(_: FastAPI):
    get_provider()  # fail fast on a misconfigured LLM (e.g. missing Gemini key)
    get_memory_provider()
    get_email_sender()  # fail fast on a half-configured SMTP
    yield


app = FastAPI(title="MemoryAI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.headers.get("content-length") and int(request.headers["content-length"]) > 1_000_000:
        return JSONResponse({"detail": "Request body is too large"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Request-ID"] = str(uuid.uuid4())
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(conversations.router)
app.include_router(messages.router)
app.include_router(memories.router)
app.include_router(analytics.router)
app.include_router(agents.router)
