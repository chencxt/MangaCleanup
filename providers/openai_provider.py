"""OpenAI Images Edit provider (gpt-image-1 compatible)."""
from __future__ import annotations

import base64
import io

import requests
from PIL import Image

from providers.base import BaseImageEditProvider, ProviderError
from utils.constants import DEFAULT_OPENAI_BASE_URL, DEFAULT_OPENAI_MODEL


class OpenAIEditProvider(BaseImageEditProvider):
    name = "OpenAI"

    def __init__(self, model="", api_key="", base_url="", timeout=120, size=""):
        super().__init__(
            model or DEFAULT_OPENAI_MODEL,
            api_key,
            base_url or DEFAULT_OPENAI_BASE_URL,
            timeout,
            size,
        )

    def edit(self, image: Image.Image, prompt: str) -> Image.Image:
        if not self.api_key:
            raise ProviderError("OpenAI API Key 为空")
        size = self.resolved_size("auto")
        if size != "auto":
            parts = size.split("x")
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                raise ProviderError(f"分辨率 {size!r} 不适用于 OpenAI，请用 WxH 格式 (如 1024x1536) 或留空=auto")
        url = f"{self.base_url}/images/edits"
        png = self.to_png_bytes(image)
        files = {"image": ("input.png", io.BytesIO(png), "image/png")}
        data = {"model": self.model, "prompt": prompt, "n": "1", "size": size}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            r = requests.post(url, headers=headers, files=files, data=data, timeout=self.timeout)
        except requests.RequestException as e:
            raise ProviderError(f"OpenAI 请求异常: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"OpenAI HTTP {r.status_code}: {r.text[:500]}")
        ctype = r.headers.get("Content-Type", "")
        if ctype.startswith("image/"):
            out = self.from_bytes(r.content)
            return self.fit_back(out, image.size)
        try:
            payload = r.json()
        except Exception as e:
            raise ProviderError(f"OpenAI 返回解析失败: {r.text[:500]}") from e
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
                raise ProviderError(f"OpenAI 图片下载失败: {e}") from e
        raise ProviderError(f"OpenAI 返回无可用图像: {str(payload)[:500]}")
