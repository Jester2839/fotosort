"""Třídění akce krok za krokem, bez printů. Volá ho CLI i GUI se svým „reporterem“."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from . import config as C
from . import cull, models


class Reporter(Protocol):
    def log(self, msg: str, level: str = "info") -> None: ...  # level: info | warn
    def progress(self, stage: str, done: int, total: int, name: str) -> None: ...


@dataclass
class CullPlan:
    folder: Path
    verdicts: list[cull.Verdict]
    series_count: int = 0
    used_ai: bool = False
    eye_errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        reasons = Counter(v.reason for v in self.verdicts if v.reason)
        return {
            "folder": str(self.folder),
            "name": self.folder.name,
            "total": len(self.verdicts),
            "good": sum(v.bucket == "good" and not v.dest for v in self.verdicts),
            "unsure": sum(v.bucket == "unsure" and not v.dest for v in self.verdicts),
            "delete": sum(reasons.values()),
            "reasons": {cull.REASONS[r]: n for r, n in reasons.most_common()},
            "untouched": sum(not v.dest and not v.bucket for v in self.verdicts),
            "series": self.series_count,
            "used_ai": self.used_ai,
        }


_scorer = None  # model se načítá ~10 s, mezi akcemi ho držíme (vždy i s kategoriemi, jsou zadarmo)


def prepare_eyes(rep: Reporter) -> str | None:
    try:
        import mediapipe  # noqa: F401
    except ImportError:
        rep.log("MediaPipe není nainstalované – zavřené oči přeskočím.", "warn")
        return None
    try:
        return str(models.ensure(models.FACE_LANDMARKER))
    except Exception as exc:
        rep.log(f"Model pro oči se nepodařilo stáhnout ({exc}) – zavřené oči přeskočím.", "warn")
        return None


def prepare_scorer(rep: Reporter):
    """Vrátí (modul ai, Scorer) nebo (None, None), když AI není k dispozici."""
    global _scorer
    try:
        from . import ai
    except ImportError as exc:
        rep.log(f"AI hodnocení vyžaduje torch a open_clip_torch ({exc}). Pokračuju bez AI.", "warn")
        return None, None
    if _scorer is not None:
        return ai, _scorer
    try:
        weights = models.ensure(models.AESTHETIC_MLP)
        rep.log("Načítám AI model (poprvé se stahuje asi 900 MB)…")
        scorer = ai.Scorer(weights, C.CATEGORIES)
    except Exception as exc:
        rep.log(f"AI model se nepodařilo načíst ({type(exc).__name__}: {exc}). Pokračuju bez AI.", "warn")
        return None, None
    if scorer.device == "cuda":
        import torch
        rep.log(f"GPU: {torch.cuda.get_device_name(0)}")
    else:
        rep.log("Běžím na CPU (torch nevidí NVIDIA GPU) – bude to pomalejší. Viz README.", "warn")
    _scorer = scorer
    return ai, scorer


def plan_cull(folder: Path, rep: Reporter, use_ai: bool = True, categories: bool = True,
              strictness: int = C.DEFAULT_STRICTNESS) -> CullPlan:
    """Analyzuje fotky přímo ve složce akce a rozhodne o každé. Nic nepřesouvá."""
    shots = cull.find_shots(folder)
    if not shots:
        return CullPlan(folder, [])

    face_model = prepare_eyes(rep) if use_ai else None
    analyses = cull.analyze_all(shots, lambda d, t, n: rep.progress("analyze", d, t, n), face_model=face_model)
    verdicts, series_count = cull.decide(shots, analyses)
    plan = CullPlan(folder, verdicts, series_count,
                    eye_errors=[a.eyes_error for a in analyses if a.eyes_error])
    if face_model and plan.eye_errors:
        rep.log(f"Detekce očí selhala u {len(plan.eye_errors)} fotek, např.: {plan.eye_errors[0]}", "warn")

    ai_mod, scorer = prepare_scorer(rep) if use_ai else (None, None)
    if scorer:
        survivors = [v for v in verdicts if not v.reason]
        scores = ai_mod.score_all([v.shot for v in survivors], scorer,
                                  lambda d, t, n: rep.progress("ai", d, t, n))
        cull.assign(survivors, scores, categories, strictness)
        plan.used_ai = True
    return plan


def apply_plan(plan: CullPlan) -> cull.ApplyReport:
    return cull.apply(plan.folder, plan.verdicts)
