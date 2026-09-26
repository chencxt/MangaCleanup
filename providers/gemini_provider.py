"""Gemini generateContent provider (image editing via inlineData)."""
from __future__ import annotations

import base64

import requests
from PIL import Image

from providers.base import BaseImageEditProvider, ProviderError
from utils.constants import DEFAULT_GEMINI_BASE_URL, DEFAULT_GEMINI_MODEL

# imageConfig.imageSize 档位 (Gemini 原生写法)
GEMINI_IMAGE_SIZES = ("1K", "2K", "4K")

# imageConfig.aspectRatio 可选值 (Gemini 原生写法)
GEMINI_ASPECT_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9")


def _nearest_aspect(ratio: float) -> str:
    """Float w/h -> nearest Gemini aspectRatio label."""
    best, best_diff = "1:1", float("inf")
    for label in GEMINI_ASPECT_RATIOS:
        a, b = label.split(":")
        diff = abs(ratio - int(a) / int(b))
        if diff < best_diff:
            best, best_diff = label, diff
    return best


class GeminiEditProvider(BaseImageEditProvider):
    name = "Gemini"

    def __init__(self, model="", api_key="", base_url="", timeout=120, size=""):
        super().__init__(
            model or DEFAULT_GEMINI_MODEL,
            api_key,
            base_url or DEFAULT_GEMINI_BASE_URL,
            timeout,
            size,  # shared image_size field; mapped to imageConfig in edit()
        )

    def gemini_image_config(self, w: int, h: int) -> dict:
        """Map shared size string to Gemini imageConfig. {} = leave unset (model default).

        Accepts both styles:
        - OpenAI style "1024x1536" -> nearest aspectRatio + 1K/2K/4K by long side
        - Gemini style "1K"/"2K"/"4K" (aspect falls back to source image) or "16:9" etc.
        """
        s = (self.size or "").strip().lower()
        if not s or s == "auto":
            return {}
        if "x" in s:
            parts = s.split("x")
            if len(parts) != 2:
                return {}
            try:
                sw, sh = int(parts[0]), int(parts[1])
            except ValueError:
                return {}
            if sw <= 0 or sh <= 0:
                return {}
            long_side = max(sw, sh)
            return {
                "aspectRatio": _nearest_aspect(sw / sh),
                "imageSize": "1K" if long_side <= 1024 else ("2K" if long_side <= 2048 else "4K"),
            }
        if s in ("1k", "2k", "4k"):
            return {"imageSize": s.upper(), "aspectRatio": _nearest_aspect(w / h if h else 1.0)}
        if ":" in s:
            parts = s.split(":")
            if len(parts) != 2:
                return {}
            try:
                a, b = float(parts[0]), float(parts[1])
            except ValueError:
                return {}
            if a <= 0 or b <= 0:
                return {}
            norm = f"{a:g}:{b:g}"
            for label in GEMINI_ASPECT_RATIOS:
                la, lb = label.split(":")
                if abs(a / b - int(la) / int(lb)) < 1e-9:
                    norm = label
                    break
            return {"aspectRatio": norm}
        return {}

    @staticmethod
    def _body(png: bytes, prompt: str, img_cfg: dict) -> dict:
        gen_cfg: dict = {"responseModalities": ["TEXT", "IMAGE"]}
        if img_cfg:
            gen_cfg["imageConfig"] = img_cfg
        return {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(png).decode()}},
                    ]
                }
            ],
            "generationConfig": gen_cfg,
        }

    def _post(self, url: str, headers: dict, body: dict) -> requests.Response:
        try:
            return requests.post(url, headers=headers, json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise ProviderError(f"Gemini 请求异常: {e}") from e

    def edit(self, image: Image.Image, prompt: str) -> Image.Image:
        if not self.api_key:
            raise ProviderError("Gemini API Key 为空")
        if not self.model:
            raise ProviderError("Gemini 模型名为空")
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        png = self.to_png_bytes(image)
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        img_cfg = self.gemini_image_config(image.width, image.height)
        r = self._post(url, headers, self._body(png, prompt, img_cfg))
        if r.status_code != 200 and img_cfg and r.status_code == 400 and "imageconfig" in r.text.lower():
            # 老模型不支持 imageConfig: 去掉该字段按默认重试一次
            r = self._post(url, headers, self._body(png, prompt, {}))
        if r.status_code != 200:
            raise ProviderError(f"Gemini HTTP {r.status_code}: {r.text[:800]}")
        try:
            payload = r.json()
        except Exception as e:
            raise ProviderError(f"Gemini 返回解析失败: {r.text[:500]}") from e
        if payload.get("promptFeedback", {}).get("blockReason"):
            raise ProviderError(f"Gemini 拒绝: {payload['promptFeedback']}")
        try:
            cands = payload.get("candidates", [])
            parts = cands[0].get("content", {}).get("parts", [])
        except Exception as e:
            raise ProviderError(f"Gemini 返回结构异常: {str(payload)[:500]}") from e
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                out = self.from_bytes(base64.b64decode(inline["data"]))
                return self.fit_back(out, image.size)
        raise ProviderError(f"Gemini 返回无可用图像: {str(payload)[:800]}")
