"""JSON config persistence (model name editable, provider switchable)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from utils.constants import (
    DEFAULT_GEMINI_BASE_URL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GROK_BASE_URL,
    DEFAULT_GROK_MODEL,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROMPT,
)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def default_config() -> dict:
    return {
        "provider": "OpenAI",  # OpenAI | Gemini | Grok | Mock
        "openai_model": DEFAULT_OPENAI_MODEL,
        "gemini_model": DEFAULT_GEMINI_MODEL,
        "grok_model": DEFAULT_GROK_MODEL,
        "openai_base_url": DEFAULT_OPENAI_BASE_URL,
        "gemini_base_url": DEFAULT_GEMINI_BASE_URL,
        "grok_base_url": DEFAULT_GROK_BASE_URL,
        "api_key": "",
        "remember_key": False,
        "prompt": DEFAULT_PROMPT,
        "retries": 2,
        "pad_px": 20,
        "concurrency": 3,
        "timeout": 120,
        "image_size": "",  # "" / "auto" = default; OpenAI 用 WxH, Gemini 用 1K/2K/4K·WxH·宽高比
        "output_subdir": "cleaned",
        "run_mode": "auto",  # auto | full | crop
        "recursive": False,
        "model_history": [],
    }


def load_config() -> dict:
    cfg = default_config()
    try:
        if CONFIG_PATH.exists():
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in loaded.items() if k in cfg})
    except Exception:
        pass
    # Env fallback for keys (never overwrite explicit saved key)
    if not cfg.get("api_key"):
        if cfg.get("provider") == "OpenAI":
            cfg["api_key"] = os.getenv("OPENAI_API_KEY", "")
        elif cfg.get("provider") == "Grok":
            cfg["api_key"] = os.getenv("XAI_API_KEY", "")
        else:
            cfg["api_key"] = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    return cfg


def save_config(cfg: dict) -> None:
    data = {k: cfg.get(k) for k in default_config()}
    if not cfg.get("remember_key"):
        data["api_key"] = ""
    try:
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
