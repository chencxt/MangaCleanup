"""Offline mock provider (no network) for pipeline self-test."""
from __future__ import annotations

from PIL import Image, ImageDraw

from providers.base import BaseImageEditProvider


class MockEditProvider(BaseImageEditProvider):
    name = "Mock"

    def edit(self, image: Image.Image, prompt: str) -> Image.Image:
        # Simulate a "clean": return a copy (keeps size contract).
        return image.copy()
