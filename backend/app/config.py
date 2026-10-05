from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_origins: str = "http://localhost:5173"
    database_url: str = "postgresql+asyncpg://memoryai:memoryai@localhost:5432/memoryai"
    # No default on purpose: the app refuses to start without a real secret.
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    cookie_secure: bool = False  # set COOKIE_SECURE=true behind HTTPS

    # Password reset + email. "console" prints emails to the backend log (dev only); "smtp" sends real mail.
    frontend_url: str = "http://localhost:5173"  # base of the link inside reset emails
    reset_token_minutes: int = 30
    reset_cooldown_seconds: int = 60  # at most one reset email per account per minute (proper rate limits: Stage 10)
    email_backend: Literal["console", "smtp"] = "console"
    email_from: str = "MemoryAI <no-reply@localhost>"
    smtp_host: str = ""
    smtp_port: int = 587  # STARTTLS. (Implicit-TLS port 465 is not supported.)
    smtp_username: str = ""
    smtp_password: str = ""

    # LLM. Default is the offline fake so the app runs with zero setup and zero cost.
    llm_provider: Literal["fake", "gemini", "ollama"] = "fake"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"  # check AI Studio for models available on your key
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    max_output_tokens: int = 800
    max_history_messages: int = 20  # bounded context window
    max_message_chars: int = 8000

    # Memory. "fake" = in-process keyword matcher for tests/offline. "mem0" needs requirements-mem0.txt.
    memory_provider: Literal["fake", "mem0", "custom"] = "fake"
    memory_top_k: int = 5
    memory_threshold: float = 0.3
    memory_timeout_seconds: float = 8.0
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_provider: Literal["fake", "fastembed"] = "fake"
    embedding_dims: int = 384  


    # Custom memory: relevance = w_sim*similarity + w_imp*importance + w_rec*recency + w_pin*pinned
    memory_min_similarity: float = 0.45  # cosine similarity gate; calibrate per embedding model (Stage 9 eval)
    memory_w_similarity: float = 0.70
    memory_w_importance: float = 0.15
    memory_w_recency: float = 0.10
    memory_w_pinned: float = 0.05
    memory_recency_half_life_days: float = 60.0
    memory_max_per_exchange: int = 5
    # De-duplication bands (cosine similarity to the nearest existing memory). Uncalibrated until the Stage 9 eval.
    memory_auto_merge_similarity: float = 0.92  # at or above: same fact, merge without asking the LLM
    memory_review_similarity: float = 0.65  # between this and auto-merge: ask the LLM same / different / conflicting

    # Stage 10: deliberately process-local. Swap this small interface for Redis when deploying multiple workers.
    rate_limit_chat_per_minute: int = 12
    rate_limit_import_per_minute: int = 3
    daily_request_budget: int = 120
    max_import_memories: int = 500


settings = Settings()  # type: ignore[call-arg]
