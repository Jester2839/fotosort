"""Třídění složky akce.

Vyřazené (neostré, série, zavřené oči, přepálené JPG, slabé AI skóre) se přesunou do
_ke_smazani/<důvod>/. Všechno ostatní skončí v _vyber/ a výběr s nejistými dostanou XMP pro Lightroom.
Nic se nemaže. Každý přesun i zápis XMP jde do logu, takže jde celé vrátit (undo).
"""

from __future__ import annotations

import csv
import math
import os
import statistics
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config as C
from . import xmp
from .analyze import Analysis, analyze, hamming
from .media import Shot, collect_photos

REASONS = {"neostre": "neostré", "zavrene_oci": "zavřené oči", "serie": "ze série",
           "expozice": "přepálené/podexponované JPG", "slabe": "nízké AI skóre", "chyba": "nejde načíst"}


@dataclass
class Score:
    """Výsledek AI pro jeden snímek (počítá ai.Scorer; tady, aby třídění nepotřebovalo torch)."""

    aesthetic: float | None
    category: str = ""
    category_prob: float = 0.0


@dataclass
class Verdict:
    shot: Shot
    analysis: Analysis
    reason: str = ""  # důvod vyřazení; prázdné = nevyřazeno
    note: str = ""
    dest: str = ""  # cílová podsložka relativně ke složce akce; prázdné = nechat na místě
    bucket: str = ""  # "good" | "unsure" (zůstává na místě, dostane XMP); prázdné = bez AI
    score: float | None = None  # AI estetické skóre
    category: str = ""

    def reject(self, reason: str, note: str) -> None:
        self.reason, self.note = reason, note
        self.dest = f"{C.CULL_FOLDERS['delete']}/{reason}"


def event_folder(folder: Path) -> Path:
    """Složka akce, i když uživatel vybral přímo její _vyber."""
    return folder.parent if folder.name.lower() == C.PHOTO_SUBFOLDER.lower() else folder


def find_shots(folder: Path) -> list[Shot]:
    """Fotky v _vyber a přímo ve složce akce (starší akce), ne v _upraveno, _ke_smazani…"""
    shots = collect_photos(folder, recursive=False)
    if (folder / C.PHOTO_SUBFOLDER).is_dir():
        shots += collect_photos(folder / C.PHOTO_SUBFOLDER, recursive=False)
    return sorted(shots, key=lambda s: s.taken)


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
    pool = ProcessPoolExecutor(max_workers=workers, initializer=_quiet_worker)
    try:
        futures = {pool.submit(analyze, s.files, face_model): i for i, s in enumerate(shots)}
        for done, fut in enumerate(as_completed(futures), 1):
            i = futures[fut]
            results[i] = fut.result()
            if progress:  # progress smí vyhodit výjimku (zrušení z GUI)
                progress(done, len(shots), shots[i].stem)
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown()
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


def assign(verdicts: list[Verdict], scores: list[Score], use_categories: bool,
           strictness: int = C.DEFAULT_STRICTNESS) -> None:
    """Rozdělí technicky OK fotky podle pořadí AI skóre v rámci focení (relativně, ne absolutně).

    `scores` jsou ve stejném pořadí jako verdikty.
    """
    top_share, bottom_share = C.STRICTNESS[strictness]
    scored = []
    for v, s in zip(verdicts, scores):
        v.score, v.category = s.aesthetic, (s.category if use_categories else "")
        if s.aesthetic is None:
            v.bucket, v.note = "unsure", "AI náhled nejde načíst"
        else:
            scored.append((v, s))

    scored.sort(key=lambda vs: vs[0].score, reverse=True)
    n = len(scored)
    top = math.ceil(n * top_share)
    bottom = math.floor(n * bottom_share) if n >= 10 else 0  # u pár fotek nic nevyhazovat
    for rank, (v, s) in enumerate(scored):
        note = f"skóre {v.score:.2f}"
        if v.category:
            note += f" · {v.category} {s.category_prob:.0%}"
        if rank < top and v.score >= C.VYBER_MIN_SCORE:
            v.bucket, v.note = "good", note
        elif rank >= n - bottom and v.score < C.SLABE_MAX_SCORE:
            v.reject("slabe", note)
        else:
            v.bucket, v.note = "unsure", note


def keywords_for(v: Verdict) -> list[xmp.Keyword]:
    root = C.KEYWORD_ROOT
    kws: list[xmp.Keyword] = [(root, C.BUCKET_KEYWORD[v.bucket])]
    if v.category:
        kws.append((root, "Obsah", C.CATEGORY_KEYWORD.get(v.category, v.category)))
    return kws


@dataclass
class ApplyReport:
    moved: int = 0  # přesunuté soubory (do _ke_smazani)
    tagged: int = 0  # snímky s nově zapsaným XMP
    foreign_xmp: list[str] = field(default_factory=list)  # už měly cizí XMP (nechány být)


def apply(folder: Path, verdicts: list[Verdict]) -> ApplyReport:
    """Vyřazené do _ke_smazani/<důvod>, ostatní do _vyber (RAW+JPG spolu), XMP výběru/nejistým.

    Každý krok jde do logu (cesty relativně ke složce akce), undo ho přehraje pozpátku.
    """
    log_path = folder / C.CULL_FOLDERS["delete"] / C.CULL_LOG
    log_path.parent.mkdir(exist_ok=True)
    new_log = not log_path.exists()
    report = ApplyReport()
    with log_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_log:
            writer.writerow(["z", "do", "duvod", "poznamka"])
        for v in verdicts:
            target = folder / (v.dest or C.PHOTO_SUBFOLDER)
            target.mkdir(parents=True, exist_ok=True)
            files = []
            sidecars = [x for x in {f.with_suffix(".xmp") for f in v.shot.files} if x.exists()]
            for f in [*v.shot.files, *sidecars]:  # existující .xmp (např. z LR) jde s fotkou
                dst = target / f.name
                if f.parent == target or dst.exists():
                    files.append(f)
                    continue
                os.replace(f, dst)
                writer.writerow([f.relative_to(folder).as_posix(), dst.relative_to(folder).as_posix(),
                                 v.reason or "vyber", v.note])
                files.append(dst)
                report.moved += 1
            v.shot.files = files = [f for f in files if f.suffix.lower() != ".xmp"]
            if v.bucket and not v.dest:
                written = xmp.write(files, C.XMP_RATING[v.bucket], keywords_for(v))
                if written is None:
                    report.foreign_xmp.append(v.shot.stem)
                    continue
                writer.writerow([written.relative_to(folder).as_posix(), "xmp", v.bucket, v.note])
                report.tagged += 1
    return report


def undo(folder: Path) -> int:
    """Vrátí všechny přesuny z logu zpět do složky akce a odstraní naše XMP."""
    log_path = folder / C.CULL_FOLDERS["delete"] / C.CULL_LOG
    if not log_path.exists():
        log_path = folder / ".fotosort_log.csv"  # starší verze ho dávala do složky akce
    if not log_path.exists():
        return 0
    restored = 0
    with log_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in reversed(rows):  # pozpátku: XMP se odstraní dřív, než se soubor vrátí
        if row["do"] == "xmp":
            restored += xmp.remove(folder / row["z"])
            continue
        src, dst = folder / row["do"], folder / row["z"]
        if src.exists() and not dst.exists():
            os.replace(src, dst)
            restored += 1
    log_path.unlink()
    for top in (*C.CULL_FOLDERS.values(), *C.LEGACY_CULL_FOLDERS):
        base = folder / top
        for sub in sorted(base.glob("**/"), reverse=True) if base.exists() else []:
            if not any(sub.iterdir()):
                sub.rmdir()
    return restored


def is_culled(folder: Path) -> bool:
    return (folder / C.CULL_FOLDERS["delete"] / C.CULL_LOG).exists()
