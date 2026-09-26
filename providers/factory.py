"""Provider factory: OpenAI / Gemini / Grok / Mock, model name pass-through."""
from __future__ import annotations

from providers.base import BaseImageEditProvider
from providers.gemini_provider import GeminiEditProvider
from providers.grok_provider import GrokEditProvider
from providers.mock_provider import MockEditProvider
from providers.openai_provider import OpenAIEditProvider
from utils.constants import DEFAULT_GEMINI_BASE_URL, DEFAULT_GROK_BASE_URL, DEFAULT_OPENAI_BASE_URL


def create_provider(
    provider: str,
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    timeout: int = 120,
    size: str = "",
) -> BaseImageEditProvider:
    p = (provider or "").strip().lower()
    if p.startswith("gemini"):
        return GeminiEditProvider(model, api_key, base_url or DEFAULT_GEMINI_BASE_URL, timeout, size)
    if p.startswith("grok"):
        return GrokEditProvider(model, api_key, base_url or DEFAULT_GROK_BASE_URL, timeout, size)
    if p.startswith("mock"):
        return MockEditProvider(model, api_key, base_url, timeout, size)
    return OpenAIEditProvider(model, api_key, base_url or DEFAULT_OPENAI_BASE_URL, timeout, size)
