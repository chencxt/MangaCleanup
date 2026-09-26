"""Crop / refill helpers: norm boxes -> pixel boxes with pad + clamp."""
from __future__ import annotations

from PIL import Image

from core.neko import NekoBox


def norm_to_pixels(
    box: NekoBox, img_w: int, img_h: int, pad_px: int = 20, min_size: int = 32
) -> tuple[int, int, int, int]:
    x0 = int(box.left * img_w) - pad_px
    y0 = int(box.top * img_h) - pad_px
    x1 = int((box.left + box.width) * img_w) + pad_px
    y1 = int((box.top + box.height) * img_h) + pad_px
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img_w, x1), min(img_h, y1)
    # enforce minimum size centred on box (clamped)
    if x1 - x0 < min_size:
        cx = (x0 + x1) // 2
        x0 = max(0, cx - min_size // 2)
        x1 = min(img_w, x0 + min_size)
        x0 = max(0, x1 - min_size)
    if y1 - y0 < min_size:
        cy = (y0 + y1) // 2
        y0 = max(0, cy - min_size // 2)
        y1 = min(img_h, y0 + min_size)
        y0 = max(0, y1 - min_size)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"无效截取框: {box}")
    return x0, y0, x1, y1


def boxes_to_pixels(
    boxes: list[NekoBox], img_w: int, img_h: int, pad_px: int = 20
) -> list[tuple[int, int, int, int]]:
    out = []
    for b in boxes:
        try:
            out.append(norm_to_pixels(b, img_w, img_h, pad_px))
        except ValueError:
            continue
    return out


def refill_image(
    base: Image.Image,
    cleaned_patches: list[Image.Image | None],
    pixel_boxes: list[tuple[int, int, int, int]],
) -> Image.Image:
    result = base.copy()
    for patch, (x0, y0, x1, y1) in zip(cleaned_patches, pixel_boxes):
        if patch is None:
            continue  # failed patch keeps original pixels
        w, h = x1 - x0, y1 - y0
        if patch.size != (w, h):
            patch = patch.resize((w, h), Image.LANCZOS)
        result.paste(patch, (x0, y0))
    return result
