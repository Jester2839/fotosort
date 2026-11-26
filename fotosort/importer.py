"""Import z karty do knihovny: plán (bez zápisu) a bezpečné kopírování s ověřením."""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from .config import EVENT_SUBFOLDERS_ON_IMPORT, VIDEO_SUBFOLDER
from .media import Shot
from .naming import dest_filename, event_path

CHUNK = 4 * 1024 * 1024
ProgressFn = Callable[[int, int, str], None]  # (hotovo bajtů, celkem bajtů, aktuální soubor)


class ImportAborted(Exception):
    """Kopírování se přerušilo (vytažená karta, plný disk…). Rozkopírovaný soubor je smazán."""


@dataclass
class Event:
    shots: list[Shot]
    name: str = ""

    @property
    def start(self) -> date:
        return min(s.taken for s in self.shots).date()

    @property
    def end(self) -> date:
        return max(s.taken for s in self.shots).date()

    def path(self, root: Path) -> Path:
        return event_path(root, self.start, self.end, self.name)

    @property
    def photo_count(self) -> int:
        return sum(1 for s in self.shots if not s.is_video)

    @property
    def video_count(self) -> int:
        return sum(1 for s in self.shots if s.is_video)


@dataclass
class Report:
    copied: int = 0
    skipped: int = 0
    folders: list[Path] = field(default_factory=list)


def library_index(root: Path) -> set[str]:
    """Názvy všech souborů v knihovně (jen výpis adresářů, nic se nečte ani nestahuje z OneDrive)."""
    names: set[str] = set()
    if root.is_dir():
        for _, _, files in os.walk(root):
            names.update(f.lower() for f in files)
    return names


def is_imported(shot: Shot, index: set[str]) -> bool:
    return all(dest_filename(f, shot.taken).lower() in index for f in shot.files)


def split_new(shots: list[Shot], index: set[str]) -> tuple[list[Shot], list[Shot]]:
    new, old = [], []
    for s in shots:
        (old if is_imported(s, index) else new).append(s)
    return new, old


def total_bytes(events: list[Event]) -> int:
    return sum(s.size for e in events for s in e.shots)


def check_free_space(root: Path, needed: int) -> tuple[bool, int]:
    probe = root
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    return free > needed * 1.05, free


def _hash_file(path: Path) -> str:
    h = hashlib.blake2b(digest_size=16)
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def copy_verified(src: Path, dst: Path, on_chunk: Callable[[int], None] = lambda n: None) -> None:
    """Kopíruje přes .part soubor, hashuje při čtení z karty a pak ověří zapsaný soubor."""
    tmp = dst.with_name(dst.name + ".part")
    h = hashlib.blake2b(digest_size=16)
    try:
        with src.open("rb") as fin, tmp.open("wb") as fout:
            while chunk := fin.read(CHUNK):
                h.update(chunk)
                fout.write(chunk)
                on_chunk(len(chunk))
            fout.flush()
            os.fsync(fout.fileno())
        if _hash_file(tmp) != h.hexdigest():
            raise ImportAborted(f"Kontrolní součet nesedí: {src.name}")
        shutil.copystat(src, tmp)
        os.replace(tmp, dst)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ImportAborted(f"Kopírování {src.name} selhalo: {exc}") from exc
    except ImportAborted:
        tmp.unlink(missing_ok=True)
        raise


def run_import(events: list[Event], root: Path, progress: ProgressFn | None = None) -> Report:
    report = Report()
    total = total_bytes(events)
    done = 0

    def tick(n: int) -> None:
        nonlocal done
        done += n

    for event in events:
        folder = event.path(root)
        folder.mkdir(parents=True, exist_ok=True)
        for sub in EVENT_SUBFOLDERS_ON_IMPORT:
            (folder / sub).mkdir(exist_ok=True)
        report.folders.append(folder)

        for shot in event.shots:
            target_dir = folder / VIDEO_SUBFOLDER if shot.is_video else folder
            target_dir.mkdir(exist_ok=True)
            for src in shot.files:
                dst = target_dir / dest_filename(src, shot.taken)
                if progress:
                    progress(done, total, src.name)
                if dst.exists():
                    report.skipped += 1
                    done += src.stat().st_size
                    continue
                copy_verified(src, dst, tick)
                report.copied += 1
    if progress:
        progress(total, total, "")
    return report
