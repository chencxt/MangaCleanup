"""Neko project parsing: .neko is a zip; texts.json path varies."""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NekoBox:
    """One text region, normalized 0~1 coords. Prefers bubbleBox, falls back to box."""

    left: float
    top: float
    width: float
    height: float
    used_bubble: bool = True
    raw: dict = field(default_factory=dict)


@dataclass
class NekoProject:
    neko_path: Path
    uid_to_name: dict[str, str]  # imageUid -> "name.ext"
    ordered_uids: list[str]      # by project index (fallback for order matching)
    boxes_by_uid: dict[str, list[NekoBox]]
    image_count: int = 0
    translation_count: int = 0


def _find_in_zip(z: zipfile.ZipFile, target: str) -> str | None:
    target = target.lower()
    names = z.namelist()
    for n in names:  # exact-name match first
        if n.lower() == target or n.lower().endswith("/" + target):
            return n
    for n in names:  # suffix match (texts.json may sit in subfolder)
        if n.lower().endswith(target):
            return n
    return None


def _pick_box(t: dict) -> NekoBox | None:
    def f(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    bw, bh = f(t.get("bubbleBoxWidth")), f(t.get("bubbleBoxHeight"))
    if bw > 0 and bh > 0 and t.get("bubbleBoxLeft") is not None:
        return NekoBox(f(t.get("bubbleBoxLeft")), f(t.get("bubbleBoxTop")), bw, bh, True, t)
    w, h = f(t.get("boxWidth")), f(t.get("boxHeight"))
    if w > 0 and h > 0:
        return NekoBox(f(t.get("boxLeft")), f(t.get("boxTop")), w, h, False, t)
    return None


def load_neko(neko_path: str | Path) -> NekoProject:
    neko_path = Path(neko_path)
    if not neko_path.is_file():
        raise FileNotFoundError(f"neko 文件不存在: {neko_path}")
    try:
        z = zipfile.ZipFile(neko_path)
    except zipfile.BadZipFile as e:
        raise ValueError(f"neko 不是有效压缩包: {neko_path} ({e})") from e
    with z:
        texts_name = _find_in_zip(z, "texts.json")
        if not texts_name:
            raise ValueError(f"{neko_path.name} 中未找到 texts.json（内容: {z.namelist()[:10]})")
        try:
            texts = json.loads(z.read(texts_name).decode("utf-8", errors="ignore"))
        except Exception as e:
            raise ValueError(f"texts.json 解析失败: {e}") from e

        uid_to_name: dict[str, str] = {}
        ordered_uids: list[str] = []
        proj_name = _find_in_zip(z, "project.json")
        if proj_name:
            try:
                proj = json.loads(z.read(proj_name).decode("utf-8", errors="ignore"))
                imgs: list[dict] = []
                for v in proj.get("volumes", []):
                    for c in v.get("chapters", []):
                        imgs.extend(c.get("images", []))
                imgs.sort(key=lambda d: d.get("index", 0))
                for im in imgs:
                    uid = str(im.get("uid", ""))
                    if not uid:
                        continue
                    fname = f"{im.get('name', uid)}.{im.get('ext', 'jpg')}"
                    uid_to_name[uid] = fname
                    ordered_uids.append(uid)
            except Exception:
                pass  # project.json optional; order fallback still works via texts.json

        boxes_by_uid: dict[str, list[NekoBox]] = {}
        pages = texts.get("pages", []) if isinstance(texts, dict) else []
        for page in pages:
            uid = str(page.get("imageUid", ""))
            if not uid:
                continue
            if uid not in ordered_uids:
                ordered_uids.append(uid)
            boxes: list[NekoBox] = []
            for t in page.get("translations", []):
                if not isinstance(t, dict):
                    continue
                if t.get("noTextDetected"):
                    continue
                b = _pick_box(t)
                if b:
                    boxes.append(b)
            boxes_by_uid[uid] = boxes

    n_trans = sum(len(v) for v in boxes_by_uid.values())
    return NekoProject(
        neko_path=neko_path,
        uid_to_name=uid_to_name,
        ordered_uids=ordered_uids,
        boxes_by_uid=boxes_by_uid,
        image_count=len(ordered_uids),
        translation_count=n_trans,
    )
