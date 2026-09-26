"""Grok (xAI) images/edits provider.

Note: xAI image editing requires application/json with `image_url`
(base64 data URI); OpenAI-style multipart uploads are NOT supported,
so this cannot reuse OpenAIEditProvider.
"""
from __future__ import annotations

import base64

import requests
from PIL import Image

from providers.base import BaseImageEditProvider, ProviderError
from utils.constants import DEFAULT_GROK_BASE_URL, DEFAULT_GROK_MODEL

# resolution only supports 1k/2k (no 4K); 4k input is clamped to 2k.
GROK_RESOLUTIONS = ("1k", "2k")

GROK_ASPECT_RATIOS = (
    "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "2:1", "1:2", "5:2",
)


def _nearest_aspect(ratio: float) -> str:
    """Float w/h -> nearest Grok aspect_ratio label."""
    best, best_diff = "1:1", float("inf")
    for label in GROK_ASPECT_RATIOS:
        a, b = label.split(":")
        diff = abs(ratio - float(a) / float(b))
        if diff < best_diff:
            best, best_diff = label, diff
    return best


class GrokEditProvider(BaseImageEditProvider):
    name = "Grok"

    def __init__(self, model="", api_key="", base_url="", timeout=120, size=""):
        super().__init__(
            model or DEFAULT_GROK_MODEL,
            api_key,
            base_url or DEFAULT_GROK_BASE_URL,
            timeout,
            size,  # shared image_size field; mapped to aspect_ratio/resolution in edit()
        )

    def grok_image_config(self, w: int, h: int) -> dict:
        """Map shared size string to Grok params. {} = omit both (server defaults).

        Accepts all three styles:
        - OpenAI style "1024x1536" -> nearest aspect_ratio + 1k/2k by long side
        - Grok style "1k"/"2k" (aspect falls back to source image; "4k" clamps to 2k)
        - Aspect style "16:9" etc. -> aspect_ratio only
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
            return {
                "aspect_ratio": _nearest_aspect(sw / sh),
                "resolution": "1k" if max(sw, sh) <= 1024 else "2k",
            }
        if s in ("1k", "2k", "4k"):
            return {"resolution": "2k" if s == "4k" else s, "aspect_ratio": _nearest_aspect(w / h if h else 1.0)}
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
            for label in GROK_ASPECT_RATIOS:
                la, lb = label.split(":")
                if abs(a / b - float(la) / float(lb)) < 1e-9:
                    norm = label
                    break
            return {"aspect_ratio": norm}
        return {}

    @staticmethod
    def _body(png: bytes, prompt: str, model: str, img_cfg: dict) -> dict:
        body: dict = {
            "model": model,
            "prompt": prompt,
            "image_url": "data:image/png;base64," + base64.b64encode(png).decode(),
            "n": 1,
            "response_format": "b64_json",
        }
        if img_cfg.get("aspect_ratio"):
            body["aspect_ratio"] = img_cfg["aspect_ratio"]
        if img_cfg.get("resolution"):
            body["resolution"] = img_cfg["resolution"]
        return body

    def _post(self, url: str, headers: dict, body: dict) -> requests.Response:
        try:
            return requests.post(url, headers=headers, json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise ProviderError(f"Grok 请求异常: {e}") from e

    def edit(self, image: Image.Image, prompt: str) -> Image.Image:
        if not self.api_key:
            raise ProviderError("Grok API Key 为空")
        if not self.model:
            raise ProviderError("Grok 模型名为空")
        url = f"{self.base_url}/images/edits"
        png = self.to_png_bytes(image)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        img_cfg = self.grok_image_config(image.width, image.height)
        r = self._post(url, headers, self._body(png, prompt, self.model, img_cfg))
        if r.status_code != 200 and img_cfg and r.status_code == 400 and ("aspect_ratio" in r.text or "resolution" in r.text):
            # 尺寸参数不被接受: 去掉后按默认重试一次
            r = self._post(url, headers, self._body(png, prompt, self.model, {}))
        if r.status_code != 200:
            raise ProviderError(f"Grok HTTP {r.status_code}: {r.text[:800]}")
        try:
            payload = r.json()
        except Exception as e:
            raise ProviderError(f"Grok 返回解析失败: {r.text[:500]}") from e
        datum = (payload.get("data") or [{}])[0]
        b64 = datum.get("b64_json")
        if b64:
            out = self.from_bytes(base64.b64decode(b64))
            return self.fit_back(out, image.size)
        url2 = datum.get("url")
        if url2:
            try:
                r2 = requests.get(url2, timeout=self.timeout)
                r2.raise_for_status()
                out = self.from_bytes(r2.content)
                return self.fit_back(out, image.size)
            except requests.RequestException as e:
                raise ProviderError(f"Grok 图片下载失败: {e}") from e
        raise ProviderError(f"Grok 返回无可用图像: {str(payload)[:500]}")
