"""Pevné pojmenování podle existující knihovny: 260501-03_machov, 260812_zatmeni slunce."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_name(name: str) -> str:
    """Odstraní znaky, které Windows v názvu složky nesnese."""
    name = _INVALID.sub("", name).strip()
    return name.rstrip(". ")


def date_range_label(start: date, end: date) -> str:
    """260812 | 260813-16 | 260730-0802 | 251230-260102"""
    first = start.strftime("%y%m%d")
    if end == start:
        return first
    if (end.year, end.month) == (start.year, start.month):
        return f"{first}-{end:%d}"
    if end.year == start.year:
        return f"{first}-{end:%m%d}"
    return f"{first}-{end:%y%m%d}"


def event_folder_name(start: date, end: date, name: str) -> str:
    label = date_range_label(start, end)
    name = clean_name(name)
    return f"{label}_{name}" if name else label


def event_path(root: Path, start: date, end: date, name: str) -> Path:
    """Akce přes Silvestra patří do roku, kdy začala."""
    return root / str(start.year) / event_folder_name(start, end, name)


def dest_filename(original: Path, taken: datetime) -> str:
    """DSC01234.ARW -> 260712_143502_DSC01234.ARW

    Sony počítadlo se po 9999 přetočí; čas v názvu brání kolizím a řadí soubory chronologicky.
    """
    return f"{taken:%y%m%d_%H%M%S}_{original.name}"
