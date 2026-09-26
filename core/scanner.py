"""Folder scanning: images list + neko matching (name-first, order fallback)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from core.neko import NekoProject
from utils.constants import IMAGE_EXTS


@dataclass
class ImageItem:
    path: Path
    name: str
    stem_key: str  # lower stem for matching
    width: int = 0
    height: int = 0
    neko_uid: str = ""
    match_method: str = "none"  # name | order | none
    box_count: int = 0
    force_crop: bool = False


def scan_images(input_dir: str | Path, recursive: bool = False) -> list[ImageItem]:
    root = Path(input_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"输入路径不是文件夹: {root}")
    pattern = "**/*" if recursive else "*"
    items: list[ImageItem] = []
    for p in sorted(root.glob(pattern)):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        if p.name.startswith("."):
            continue
        item = ImageItem(path=p, name=p.name, stem_key=p.stem.strip().lower())
        try:
            with Image.open(p) as im:
                item.width, item.height = im.size
        except Exception:
            pass
        items.append(item)
    return items


def find_neko_files(search_dir: str | Path) -> list[Path]:
    root = Path(search_dir)
    if not root.is_dir():
        return []
    return sorted(root.glob("*.neko"))


def attach_neko(items: list[ImageItem], neko: NekoProject | None) -> list[ImageItem]:
    """Fill neko_uid/match_method/box_count. Never raises for lookup failures."""
    if neko is None:
        return items
    # name -> uid index (strip ext, lowercase)
    name_to_uid: dict[str, str] = {}
    for uid, fname in neko.uid_to_name.items():
        name_to_uid[Path(fname).stem.strip().lower()] = uid
    # order fallback list
    ordered = list(neko.ordered_uids)
    if not ordered:
        ordered = list(neko.boxes_by_uid.keys())
    used_order: set[str] = set()
    for i, item in enumerate(items):
        uid = name_to_uid.get(item.stem_key, "")
        if uid:
            item.neko_uid = uid
            item.match_method = "name"
        elif i < len(ordered):
            cand = ordered[i]
            if cand not in used_order:
                item.neko_uid = cand
                item.match_method = "order"
                used_order.add(cand)
        boxes = neko.boxes_by_uid.get(item.neko_uid, []) if item.neko_uid else []
        item.box_count = len(boxes)
    return items
