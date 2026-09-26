"""Provider abstraction for image-edit models."""
from __future__ import annotations

import io
from abc import ABC, abstractmethod

from PIL import Image


class ProviderError(RuntimeError):
    pass


class BaseImageEditProvider(ABC):
    name = "base"

    def __init__(self, model: str = "", api_key: str = "", base_url: str = "", timeout: int = 120, size: str = ""):
        self.model = (model or "").strip()
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.timeout = timeout
        self.size = (size or "").strip().lower()

    @abstractmethod
    def edit(self, image: Image.Image, prompt: str) -> Image.Image:
        """Send one PIL image + prompt, return cleaned PIL image."""

    # -- helpers --
    @staticmethod
    def to_png_bytes(image: Image.Image) -> bytes:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def from_bytes(data: bytes) -> Image.Image:
        return Image.open(io.BytesIO(data)).convert("RGB")

    @staticmethod
    def fit_back(img: Image.Image, target_size: tuple[int, int]) -> Image.Image:
        if img.size != target_size:
            img = img.resize(target_size, Image.LANCZOS)
        return img

    def resolved_size(self, default: str = "auto") -> str:
        """Return configured image size, or default when left blank. Pass-through, no validation."""
        return self.size or default


def size_for_provider(provider: str, size: str) -> str:
    """Foolproof helper: keep size only if it applies to the provider, else "" (=auto).

    - OpenAI accepts WxH only ("1024x1536"); Gemini/Grok styles ("1K", "16:9") are dropped.
    - Gemini/Grok/Mock keep everything (Gemini/Grok map WxH/1K/aspect in their
      *_image_config(); unknown text safely resolves to default at send time).
    """
    s = (size or "").strip().lower()
    if not s or s == "auto":
        return s
    p = (provider or "").strip().lower()
    if p.startswith("gemini") or p.startswith("grok") or p.startswith("mock"):
        return s
    parts = s.split("x")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return s
    return ""
