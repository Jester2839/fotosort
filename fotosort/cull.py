"""Technické třídění složky: neostré, série a přepálené JPG do _ke_smazani/<důvod>/.

Nic se nemaže. Každý přesun se zapíše do logu, takže jde celé vrátit (undo).
"""

from __future__ import annotations

import csv
import os
import statistics
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config as C
from .analyze import Analysis, analyze, hamming
from .media import Shot, collect_photos

REASONS = {"neostre": "neostré", "zavrene_oci": "zavřené oči", "serie": "ze série",
           "expozice": "přepálené/podexponované JPG", "slabe": "nízké AI skóre", "chyba": "nejde načíst"}


@dataclass
class Verdict:
    shot: Shot
    analysis: Analysis
    reason: str = ""  # důvod vyřazení; prázdné = nevyřazeno
    note: str = ""
    dest: str = ""  # cílová podsložka relativně ke složce akce; prázdné = nechat na místě
    score: float | None = None  # AI estetické skóre
    category: str = ""

    def reject(self, reason: str, note: str) -> None:
        self.reason, self.note = reason, note
        self.dest = f"{C.CULL_FOLDERS['delete']}/{reason}"


def find_shots(folder: Path) -> list[Shot]:
    """Jen fotky přímo ve složce akce, ne v podsložkách (_upraveno, _ke_smazani…)."""
    return sorted(collect_photos(folder, recursive=False), key=lambda s: s.taken)


def _quiet_worker() -> None:
    """MediaPipe/TFLite píše do stderr spoustu technických hlášek; v pracovních procesech je ztlumíme."""
    os.environ["GLOG_minloglevel"] = "3"
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)


def analyze_all(shots: list[Shot], progress: Callable[[int, int, str], None] | None = None,
                workers: int | None = None, face_model: str | None = None) -> list[Analysis]:
    results: list[Analysis] = [Analysis()] * len(shots)
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=workers, initializer=_quiet_worker) as pool:
        futures = {pool.submit(analyze, s.files, face_model): i for i, s in enumerate(shots)}
        for done, fut in enumerate(as_completed(futures), 1):
            i = futures[fut]
            results[i] = fut.result()
            if progress:
                progress(done, len(shots), shots[i].stem)
    return results


def find_series(verdicts: list[Verdict]) -> list[list[Verdict]]:
    """Řetězí po sobě jdoucí snímky: velmi rychle za sebou, nebo skoro stejné a blízko v čase."""
    series: list[list[Verdict]] = []
    current: list[Verdict] = []
    for v in verdicts:
        if current:
            prev = current[-1]
            gap = (v.shot.taken - prev.shot.taken).total_seconds()
            similar = hamming(v.analysis.dhash, prev.analysis.dhash) <= C.SIMILAR_HASH_BITS
            if gap <= C.SERIES_GAP_S or (similar and gap <= C.SIMILAR_GAP_S):
                current.append(v)
                continue
            if len(current) > 1:
                series.append(current)
        current = [v]
    if len(current) > 1:
        series.append(current)
    return series


def decide(shots: list[Shot], analyses: list[Analysis]) -> tuple[list[Verdict], int]:
    """Vrátí verdikty a počet nalezených sérií."""
    verdicts = [Verdict(s, a) for s, a in zip(shots, analyses)]
    ok = [v for v in verdicts if not v.analysis.error]
    for v in verdicts:
        if v.analysis.error:
            v.reject("chyba", v.analysis.error)

    median = statistics.median(v.analysis.sharpness for v in ok) if ok else 0

    def is_blurry(v: Verdict) -> bool:
        return v.analysis.sharpness < max(C.BLUR_ABS, C.BLUR_RELATIVE * median)

    def eyes_closed(v: Verdict) -> bool:
        return v.analysis.eyes_closed >= C.EYES_CLOSED

    def is_bad(v: Verdict) -> bool:
        return is_blurry(v) or eyes_closed(v)

    def mark_bad(v: Verdict) -> None:
        if is_blurry(v):
            v.reject("neostre", f"ostrost {v.analysis.sharpness:.0f} (medián {median:.0f})")
        else:
            v.reject("zavrene_oci", f"mrknutí {v.analysis.eyes_closed:.2f}")

    # Série první: když existuje lepší verze, důvod je "série", ne "neostré" / "zavřené oči".
    series = find_series(ok)
    in_series: set[int] = set()
    for group in series:
        in_series.update(id(v) for v in group)
        ranked = sorted(group, key=lambda v: v.analysis.sharpness, reverse=True)
        kept = [v for v in ranked if not is_bad(v)][:1 + len(group) // C.SERIES_KEEP_PER]
        if not kept:
            for v in group:
                mark_bad(v)
            continue
        kept_ids = {id(v) for v in kept}
        for v in group:
            if id(v) not in kept_ids:
                v.reject("serie", f"série {len(group)} snímků, ponechán {kept[0].shot.stem}")

    for v in ok:
        if v.reason:
            continue
        if id(v) not in in_series and is_bad(v):
            mark_bad(v)
        elif not v.shot.has_raw and v.analysis.clipped > C.CLIP_LIMIT_JPG:
            v.reject("expozice", f"{v.analysis.clipped:.0%} pixelů úplně černých/bílých")
    return verdicts, len(series)


def apply(folder: Path, verdicts: list[Verdict]) -> int:
    """Přesune snímky do jejich cílových složek (RAW+JPG spolu) a zapíše log pro undo."""
    log_path = folder / C.CULL_FOLDERS["delete"] / C.CULL_LOG
    log_path.parent.mkdir(exist_ok=True)
    new_log = not log_path.exists()
    moved = 0
    with log_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_log:
            writer.writerow(["z", "do", "duvod", "poznamka"])
        for v in verdicts:
            if not v.dest:
                continue
            target = folder / v.dest
            target.mkdir(parents=True, exist_ok=True)
            for f in v.shot.files:
                dst = target / f.name
                if dst.exists():
                    continue
                os.replace(f, dst)
                writer.writerow([f.name, dst.relative_to(folder).as_posix(), v.reason or v.dest, v.note])
                moved += 1
    return moved


def undo(folder: Path) -> int:
    """Vrátí všechny přesuny z logu zpět do složky akce."""
    log_path = folder / C.CULL_FOLDERS["delete"] / C.CULL_LOG
    if not log_path.exists():
        log_path = folder / ".fotosort_log.csv"  # starší verze ho dávala do složky akce
    if not log_path.exists():
        return 0
    restored = 0
    with log_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            src, dst = folder / row["do"], folder / row["z"]
            if src.exists() and not dst.exists():
                os.replace(src, dst)
                restored += 1
    log_path.unlink()
    for top in C.CULL_FOLDERS.values():
        base = folder / top
        for sub in sorted(base.glob("**/"), reverse=True) if base.exists() else []:
            if not any(sub.iterdir()):
                sub.rmdir()
    return restored
