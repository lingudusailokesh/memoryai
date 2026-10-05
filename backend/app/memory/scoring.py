from datetime import datetime, timezone

from app.config import Settings, settings


def relevance(similarity: float, importance: float, created_at: datetime, pinned: bool,
              now: datetime | None = None, cfg: Settings = settings) -> float:
    """final = w_sim*similarity + w_imp*importance + w_rec*recency + w_pin*pinned   (weights in config).

    recency halves every `memory_recency_half_life_days`. Similarity is gated separately by a threshold,
    so importance/recency/pinned only re-rank memories that are already relevant, never rescue irrelevant ones.
    """
    now = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created_at).total_seconds() / 86400)
    recency = 0.5 ** (age_days / cfg.memory_recency_half_life_days)
    return (cfg.memory_w_similarity * similarity + cfg.memory_w_importance * importance
            + cfg.memory_w_recency * recency + cfg.memory_w_pinned * (1.0 if pinned else 0.0))
