"""Načtení fotek a videí z karty (nebo složky) a zjištění času pořízení."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import exifread

from .config import PHOTO_EXTS, RAW_EXTS, VIDEO_EXTS

EXIF_FORMAT = "%Y:%m:%d %H:%M:%S"
_XML_DATE = re.compile(r'CreationDate\s+value="([^"]+)"')


@dataclass
class Shot:
    """Jeden snímek nebo klip. U RAW+JPG obsahuje oba soubory, aby se nikdy nerozdělily."""

    stem: str
    files: list[Path]
    taken: datetime
    is_video: bool = False
    time_from: str = "exif"  # exif | xml | mtime (mtime = nespolehlivé, ukázat varování)
    extra_files: list[Path] = field(default_factory=list)  # např. Sony XML k videu, nekopíruje se

    @property
    def size(self) -> int:
        return sum(f.stat().st_size for f in self.files)

    @property
    def has_raw(self) -> bool:
        return any(f.suffix.lower() in RAW_EXTS for f in self.files)


def read_photo_time(path: Path) -> datetime | None:
    try:
        with path.open("rb") as fh:
            tags = exifread.process_file(fh, details=False, stop_tag="EXIF DateTimeOriginal")
    except Exception:
        return None
    for key in ("EXIF DateTimeOriginal", "Image DateTime"):
        value = tags.get(key)
        if value:
            try:
                return datetime.strptime(str(value).strip(), EXIF_FORMAT)
            except ValueError:
                continue
    return None


def read_sony_video_time(xml_path: Path) -> datetime | None:
    """Sony ukládá k videu C0001M01.XML s CreationDate (např. 2026-07-12T14:35:02+02:00)."""
    try:
        match = _XML_DATE.search(xml_path.read_text(encoding="utf-8", errors="ignore"))
        if match:
            return datetime.fromisoformat(match.group(1)).replace(tzinfo=None)
    except (OSError, ValueError):
        pass
    return None


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def collect_photos(folder: Path, recursive: bool = True) -> list[Shot]:
    """Najde fotky a spáruje RAW+JPG podle složky a názvu bez přípony."""
    groups: dict[tuple[Path, str], list[Path]] = {}
    for path in (folder.rglob("*") if recursive else folder.iterdir()):
        if path.is_file() and path.suffix.lower() in PHOTO_EXTS and not path.name.startswith("."):
            groups.setdefault((path.parent, path.stem.upper()), []).append(path)

    shots = []
    for (_, stem), files in groups.items():
        # RAW má přednost při čtení EXIFu, JPG je záloha.
        files.sort(key=lambda p: p.suffix.lower() not in RAW_EXTS)
        taken, source = None, "exif"
        for f in files:
            taken = read_photo_time(f)
            if taken:
                break
        if taken is None:
            taken, source = _mtime(files[0]), "mtime"
        shots.append(Shot(stem=files[0].stem, files=files, taken=taken, time_from=source))
    return shots


def collect_sony_videos(clip_dir: Path) -> list[Shot]:
    if not clip_dir.is_dir():
        return []
    shots = []
    for path in clip_dir.iterdir():
        if not (path.is_file() and path.suffix.lower() in VIDEO_EXTS):
            continue
        xml = path.with_name(f"{path.stem}M01.XML")
        taken = read_sony_video_time(xml) if xml.exists() else None
        source = "xml"
        if taken is None:
            taken, source = _mtime(path), "mtime"
        shots.append(Shot(stem=path.stem, files=[path], taken=taken, is_video=True,
                          time_from=source, extra_files=[xml] if xml.exists() else []))
    return shots


def scan_card(card_root: Path) -> list[Shot]:
    """Sony a6700: fotky v DCIM/*, videa v PRIVATE/M4ROOT/CLIP."""
    shots = collect_photos(card_root / "DCIM") if (card_root / "DCIM").is_dir() else []
    shots += collect_sony_videos(card_root / "PRIVATE" / "M4ROOT" / "CLIP")
    shots.sort(key=lambda s: s.taken)
    return shots
