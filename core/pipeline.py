"""Batch pipeline: full-image edit with retry + auto fallback to crop-refill."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from core.crops import boxes_to_pixels, refill_image
from core.neko import NekoProject
from core.scanner import ImageItem
from providers.base import BaseImageEditProvider, ProviderError
from utils.fs import ensure_dir


@dataclass
class JobConfig:
    prompt: str
    retries: int = 2
    pad_px: int = 20
    run_mode: str = "auto"  # auto | full | crop
    output_dir: Path | str = ""
    suffix: str = "_cleaned"
    jpeg_quality: int = 95


@dataclass
class JobResult:
    item: ImageItem
    status: str  # success | failed | skipped
    message: str = ""
    output_path: str = ""
    elapsed: float = 0.0
    used_fallback: bool = False
    mode_used: str = ""


def _save_image(img: Image.Image, src: Path, output_dir: Path, suffix: str, quality: int) -> Path:
    ensure_dir(output_dir)
    ext = src.suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".png"
    out = output_dir / f"{src.stem}{suffix}{ext}"
    i = 1
    while out.exists():
        out = output_dir / f"{src.stem}{suffix}_{i}{ext}"
        i += 1
    if ext in (".jpg", ".jpeg"):
        img.convert("RGB").save(out, quality=quality)
    else:
        img.save(out)
    return out


def _full_edit(provider: BaseImageEditProvider, img: Image.Image, prompt: str, retries: int) -> Image.Image:
    last: Exception | None = None
    for _ in range(max(0, retries) + 1):
        try:
            return provider.edit(img, prompt)
        except Exception as e:
            last = e
    raise ProviderError(str(last) if last else "全图编辑失败")


def _crop_refill(
    provider: BaseImageEditProvider,
    img: Image.Image,
    boxes_norm,
    prompt: str,
    pad_px: int,
    on_patch: None = None,
) -> tuple[Image.Image, int, int]:
    pixel_boxes = boxes_to_pixels(boxes_norm, img.width, img.height, pad_px)
    if not pixel_boxes:
        raise ProviderError("无可用截取框")
    patches: list[Image.Image | None] = []
    ok = 0
    for (x0, y0, x1, y1) in pixel_boxes:
        crop = img.crop((x0, y0, x1, y1))
        try:
            cleaned = provider.edit(crop, prompt)
            if cleaned.size != (x1 - x0, y1 - y0):
                cleaned = cleaned.resize((x1 - x0, y1 - y0), Image.LANCZOS)
            patches.append(cleaned)
            ok += 1
        except Exception:
            patches.append(None)  # keep original pixels for failed patch
    return refill_image(img, patches, pixel_boxes), ok, len(pixel_boxes)


def process_one(
    item: ImageItem,
    neko: NekoProject | None,
    provider: BaseImageEditProvider,
    cfg: JobConfig,
    cancel_flag=None,
) -> JobResult:
    t0 = time.time()
    try:
        img = Image.open(item.path).convert("RGB")
    except Exception as e:
        return JobResult(item, "failed", f"读取失败: {e}", elapsed=time.time() - t0)

    force_crop = item.force_crop
    want_crop_first = cfg.run_mode == "crop" or force_crop
    boxes_norm = neko.boxes_by_uid.get(item.neko_uid, []) if (neko and item.neko_uid) else []

    def cancelled() -> bool:
        return bool(cancel_flag and cancel_flag.is_set())

    # --- crop-first path (user forced / crop-only mode) ---
    if want_crop_first:
        if not boxes_norm:
            # compatible fallback: no boxes -> full edit instead of hard fail
            try:
                out = _full_edit(provider, img, cfg.prompt, cfg.retries)
                p = _save_image(out, item.path, Path(cfg.output_dir), cfg.suffix, cfg.jpeg_quality)
                return JobResult(item, "success", "无框，已按全图处理", output_path=str(p), elapsed=time.time() - t0, used_fallback=False, mode_used="full(no-box)")
            except Exception as e:
                return JobResult(item, "failed", f"无框且全图失败: {e}", elapsed=time.time() - t0, used_fallback=False, mode_used="full(no-box)")
        if cancelled():
            return JobResult(item, "skipped", "已取消", elapsed=time.time() - t0)
        try:
            out, ok, total = _crop_refill(provider, img, boxes_norm, cfg.prompt, cfg.pad_px)
            p = _save_image(out, item.path, Path(cfg.output_dir), cfg.suffix, cfg.jpeg_quality)
            msg = f"截屏回填 {ok}/{total} 块"
            st = "success" if ok > 0 else "failed"
            if ok == 0:
                msg = "所有截块均失败"
            return JobResult(item, st, msg, output_path=str(p) if ok else "", elapsed=time.time() - t0, used_fallback=False, mode_used="crop")
        except Exception as e:
            return JobResult(item, "failed", f"截屏回填失败: {e}", elapsed=time.time() - t0, used_fallback=False, mode_used="crop")

    # --- full-first path (full-only / auto) ---
    try:
        out = _full_edit(provider, img, cfg.prompt, cfg.retries)
        p = _save_image(out, item.path, Path(cfg.output_dir), cfg.suffix, cfg.jpeg_quality)
        return JobResult(item, "success", "全图编辑成功", output_path=str(p), elapsed=time.time() - t0, used_fallback=False, mode_used="full")
    except Exception as e:
        if cfg.run_mode == "full":
            return JobResult(item, "failed", f"全图失败(重试{cfg.retries}次): {e}", elapsed=time.time() - t0, used_fallback=False, mode_used="full")
        # auto: fallback to crop-refill
        if not boxes_norm:
            return JobResult(item, "failed", f"全图失败且无框可回退: {e}", elapsed=time.time() - t0, used_fallback=True, mode_used="full")
        if cancelled():
            return JobResult(item, "skipped", "已取消", elapsed=time.time() - t0)
        try:
            out, ok, total = _crop_refill(provider, img, boxes_norm, cfg.prompt, cfg.pad_px)
            p = _save_image(out, item.path, Path(cfg.output_dir), cfg.suffix, cfg.jpeg_quality)
            if ok == 0:
                return JobResult(item, "failed", f"全图失败，回退截屏但块全失败: {e}", elapsed=time.time() - t0, used_fallback=True, mode_used="crop(fallback)")
            return JobResult(item, "success", f"全图失败已回退截屏 {ok}/{total}: {e}", output_path=str(p), elapsed=time.time() - t0, used_fallback=True, mode_used="crop(fallback)")
        except Exception as e2:
            return JobResult(item, "failed", f"全图失败，回退截屏亦失败: {e} | {e2}", elapsed=time.time() - t0, used_fallback=True, mode_used="crop(fallback)")
