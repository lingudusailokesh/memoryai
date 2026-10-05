from functools import lru_cache

from app.config import settings
from app.llm.base import LLMProvider
from app.llm.fake import FakeLLMProvider
from app.llm.gemini import GeminiProvider
from app.llm.ollama import OllamaProvider


@lru_cache
def get_provider() -> LLMProvider:
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("LLM_PROVIDER=gemini needs GEMINI_API_KEY (free key: https://aistudio.google.com)")
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model)
    return FakeLLMProvider(delay=0.03)  # small delay so streaming is visible in the UI
