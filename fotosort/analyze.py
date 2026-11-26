"""Technická analýza jednoho snímku: ostrost, otisk pro hledání sérií, expozice.

Pracuje se zmenšeným náhledem (delší strana 1024 px), aby byla čísla srovnatelná
mezi JPG v plném rozlišení a vloženým náhledem v ARW.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image, ImageOps

from .config import RAW_EXTS

PREVIEW_EDGE = 1024
TILES = 12  # mřížka 12×12: i malý ostrý subjekt na kraji (nízká clona) zabere celou dlaždici


@dataclass
class Analysis:
    sharpness: float = 0.0
    dhash: int = 0
    clipped: float = 0.0  # podíl úplně černých nebo bílých pixelů
    eyes_closed: float = -1.0  # -1 = nehodnoceno / žádný obličej
    eyes_error: str = ""
    error: str = ""


def load_preview(files: list[Path], edge: int = PREVIEW_EDGE) -> Image.Image:
    """RGB náhled. Preferuje JPG (rychlé díky draft mode), jinak vložený JPEG z ARW."""
    jpg = next((f for f in files if f.suffix.lower() not in RAW_EXTS), None)
    if jpg:
        img = Image.open(jpg)
        img.draft("RGB", (edge, edge))
    else:
        with rawpy.imread(str(files[0])) as raw:
            thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            img = Image.open(io.BytesIO(thumb.data))
        else:
            img = Image.fromarray(thumb.data)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((edge, edge))
    return img


def sharpness(gray: np.ndarray) -> float:
    """Rozptyl Laplaciánu v nejostřejších dlaždicích.

    Ne přes celý snímek: portrét s rozmazaným pozadím by jinak vyšel jako neostrý.
    """
    lap = (gray[1:-1, :-2] + gray[1:-1, 2:] + gray[:-2, 1:-1] + gray[2:, 1:-1] - 4 * gray[1:-1, 1:-1])
    h, w = lap.shape
    th, tw = h // TILES, w // TILES
    scores = sorted(
        float(lap[y * th:(y + 1) * th, x * tw:(x + 1) * tw].var())
        for y in range(TILES) for x in range(TILES)
    )
    return float(np.mean(scores[-2:]))


def dhash(img: Image.Image) -> int:
    small = np.asarray(img.resize((9, 8), Image.Resampling.BILINEAR), dtype=np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def analyze(files: list[Path], face_model: str | None = None) -> Analysis:
    try:
        rgb = load_preview(files)
    except Exception as exc:  # poškozený soubor nesmí shodit celý běh
        return Analysis(error=f"{type(exc).__name__}: {exc}")
    img = rgb.convert("L")
    gray = np.asarray(img, dtype=np.float32)
    result = Analysis(sharpness=sharpness(gray), dhash=dhash(img),
                      clipped=float(((gray <= 2) | (gray >= 253)).mean()))
    if face_model:
        try:
            from .eyes import closed_eyes_score
            result.eyes_closed = closed_eyes_score(np.asarray(rgb), face_model)
        except Exception as exc:  # oči jsou bonus; chyba detekce nesmí vyřadit fotku
            result.eyes_error = f"{type(exc).__name__}: {exc}"
    return result
