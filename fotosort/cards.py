"""Nalezení paměťové karty: disk, který má v kořeni složku DCIM."""

from __future__ import annotations

import string
import sys
from pathlib import Path


def candidate_roots() -> list[Path]:
    if sys.platform == "win32":
        return [Path(f"{letter}:\\") for letter in string.ascii_uppercase if letter not in "AB"]
    bases = [Path("/Volumes")] if sys.platform == "darwin" else [Path("/media"), Path("/run/media"), Path("/mnt")]
    roots: list[Path] = []
    for base in bases:
        if base.is_dir():
            for p in base.iterdir():
                roots.append(p)
                if p.is_dir() and not (p / "DCIM").exists():  # /media/<user>/<karta>
                    roots.extend(c for c in p.iterdir() if c.is_dir())
    return roots


def find_cards() -> list[Path]:
    cards = []
    for root in candidate_roots():
        try:
            if (root / "DCIM").is_dir():
                cards.append(root)
        except OSError:  # prázdná čtečka, nepřipojená jednotka
            continue
    return cards
