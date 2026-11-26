"""Příkazová řádka. GUI později zavolá stejné funkce z media/grouping/importer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import cards, cull, models
from . import config as C
from .config import DEFAULT_GAP_DAYS, LIBRARY_ROOT
from .grouping import Day, shooting_days, split_by_cuts, suggest_cuts
from .importer import Event, ImportAborted, check_free_space, library_index, run_import, split_new, total_bytes
from .media import scan_card

WEEKDAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def print_timeline(days: list[Day], cuts: set[int]) -> None:
    peak = max(d.count for d in days)
    for i, d in enumerate(days):
        if i in cuts:
            print("     ───────── nová akce ─────────")
        bar = "█" * max(1, round(d.count / peak * 30))
        print(f"  {i + 1:>2}. {WEEKDAYS[d.day.weekday()]} {d.day:%d.%m.%Y}  {bar} {d.count}")


def choose_cuts(days: list[Day], cuts: set[int], interactive: bool) -> set[int]:
    while True:
        print_timeline(days, cuts)
        if not interactive or len(days) == 1:
            return cuts
        answer = input("\nEnter = potvrdit. Číslo dne = začít/zrušit u něj novou akci (např. 4 9): ").strip()
        if not answer:
            return cuts
        for token in answer.replace(",", " ").split():
            if token.isdigit() and 2 <= int(token) <= len(days):
                cuts ^= {int(token) - 1}
            else:
                print(f"  ! '{token}' ignoruji (zadej číslo 2–{len(days)})")
        print()


def progress_bar(done: int, total: int, name: str) -> None:
    pct = done / total if total else 1
    sys.stdout.write(f"\r  [{'█' * int(pct * 30):<30}] {pct:4.0%}  {fmt_size(done)} / {fmt_size(total)}  {name:<28}")
    sys.stdout.flush()


def count_bar(done: int, total: int, name: str) -> None:
    pct = done / total if total else 1
    sys.stdout.write(f"\r  [{'█' * int(pct * 30):<30}] {done}/{total}  {name:<28}")
    sys.stdout.flush()


def cmd_import(args: argparse.Namespace) -> int:
    interactive = not args.yes

    if args.card:
        card = Path(args.card)
    else:
        found = cards.find_cards()
        if not found:
            print("Nenašel jsem kartu (disk se složkou DCIM). Je čtečka připojená?")
            return 1
        card = found[0]
        if len(found) > 1 and interactive:
            for i, c in enumerate(found, 1):
                print(f"  {i}. {c}")
            card = found[int(input("Kterou kartu? ") or 1) - 1]
    print(f"Karta: {card}\nKnihovna: {args.root}\n")

    shots = scan_card(card)
    if not shots:
        print("Na kartě nejsou žádné fotky ani videa.")
        return 0

    new, old = split_new(shots, library_index(args.root))
    if old:
        print(f"{len(old)} snímků už v knihovně je, ty přeskočím.")
    if not new:
        print("Všechno z karty už je importované. Hotovo.")
        return 0

    guessed = [s for s in new if s.time_from == "mtime"]
    if guessed:
        print(f"! {len(guessed)} souborů nemá datum v metadatech, beru datum souboru (může být nepřesné).")

    days = shooting_days(new)
    print(f"Nové: {sum(not s.is_video for s in new)} fotek, {sum(s.is_video for s in new)} videí "
          f"za {len(days)} dní. Návrh rozdělení (mezera ≥ {args.gap} dny bez focení = nová akce):\n")
    cuts = choose_cuts(days, suggest_cuts(days, args.gap), interactive)

    events = [Event(group) for group in split_by_cuts(new, days, cuts)]
    names = list(args.name or [])
    print()
    for i, ev in enumerate(events):
        preset = names[i] if i < len(names) else ""
        if interactive:
            label = Event(ev.shots, "").path(args.root).name
            ev.name = input(f"Název akce {label}_… : ").strip() or preset
        else:
            ev.name = preset

    needed = total_bytes(events)
    print("\nVytvořím:")
    for ev in events:
        extra = f", {ev.video_count} videí" if ev.video_count else ""
        print(f"  {ev.path(args.root)}   ({ev.photo_count} fotek{extra})")
    ok, free = check_free_space(args.root, needed)
    print(f"Celkem {fmt_size(needed)}, volno na disku {fmt_size(free)}.")
    if not ok:
        print("! Na disku není dost místa. Import neprovedu.")
        return 1
    if args.dry_run:
        print("\n(dry run – nic se nekopírovalo)")
        return 0
    if interactive and input("\nSpustit import? [A/n] ").strip().lower() not in ("", "a", "ano", "y"):
        print("Zrušeno.")
        return 0

    print()
    try:
        report = run_import(events, args.root, progress_bar)
    except ImportAborted as exc:
        print(f"\n\n✗ Import přerušen: {exc}\n  Už zkopírované soubory zůstaly; po opětovném spuštění se přeskočí.")
        return 1
    print(f"\n\n✓ Zkopírováno {report.copied} souborů, přeskočeno {report.skipped}. Karta zůstala beze změny.")
    for folder in report.folders:
        print(f"  {folder}")

    if interactive and input("\nRoztřídit nové akce hned? [a/N] ").strip().lower() in ("a", "ano", "y"):
        for folder in report.folders:
            run_cull(folder, dry_run=False, ask=True)
    return 0


def _prepare_eyes() -> str | None:
    try:
        import mediapipe  # noqa: F401
    except ImportError:
        print("  (MediaPipe není nainstalované – zavřené oči přeskočím)")
        return None
    try:
        return str(models.ensure(models.FACE_LANDMARKER))
    except Exception as exc:
        print(f"  ! Model pro oči se nepodařilo stáhnout ({exc}) – zavřené oči přeskočím")
        return None


def _prepare_scorer(categories: bool):
    try:
        from . import ai
    except ImportError as exc:
        print(f"  ! AI hodnocení vyžaduje torch a open_clip_torch ({exc}). Viz README. Pokračuju bez AI.")
        return None, None
    try:
        weights = models.ensure(models.AESTHETIC_MLP)
        print("Načítám AI model (poprvé se stahuje asi 900 MB)…")
        scorer = ai.Scorer(weights, C.CATEGORIES if categories else None)
    except Exception as exc:
        print(f"  ! AI model se nepodařilo načíst ({type(exc).__name__}: {exc}). Pokračuju bez AI.")
        return None, None
    if scorer.device == "cuda":
        import torch
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("  ! Běžím na CPU (torch nevidí NVIDIA GPU) – bude to pomalejší. Viz README, instalace torch s CUDA.")
    return ai, scorer


def _print_group(label: str, dest: str, group: list) -> None:
    print(f"  {label:<30} {len(group):>4}  → {dest}/")
    for v in group[:5]:
        print(f"      {v.shot.stem}: {v.note}")
    if len(group) > 5:
        print(f"      … a dalších {len(group) - 5}")


def run_cull(folder: Path, dry_run: bool, ask: bool, use_ai: bool = True, categories: bool = False) -> int:
    print(f"\nTřídím: {folder}")
    shots = cull.find_shots(folder)
    if not shots:
        print("Ve složce nejsou žádné fotky (podsložky se neprochází).")
        return 0

    face_model = _prepare_eyes() if use_ai else None
    print("Technická kontrola (ostrost, série, oči):")
    analyses = cull.analyze_all(shots, count_bar, face_model=face_model)
    print()
    verdicts, series_count = cull.decide(shots, analyses)
    eye_errors = [a.eyes_error for a in analyses if a.eyes_error]
    if face_model and eye_errors:
        print(f"\n  ! Detekce očí selhala u {len(eye_errors)} fotek, např.: {eye_errors[0]}")

    ai_mod, scorer = _prepare_scorer(categories) if use_ai else (None, None)
    if scorer:
        survivors = [v for v in verdicts if not v.reason]
        print("\nAI hodnocení:")
        scores = ai_mod.score_all([v.shot for v in survivors], scorer, count_bar)
        print()
        ai_mod.assign(survivors, scores, categories)

    print(f"\n\nAnalyzováno {len(shots)} snímků, nalezeno {series_count} sérií.")
    trash = C.CULL_FOLDERS["delete"]
    for reason, label in cull.REASONS.items():
        group = [v for v in verdicts if v.reason == reason]
        if group:
            _print_group(label, f"{trash}/{reason}", group)
    if scorer:
        unsure = [v for v in verdicts if v.dest == C.CULL_FOLDERS["unsure"]]
        good = [v for v in verdicts if v.dest.startswith(C.CULL_FOLDERS["good"])]
        if categories:
            for dest in sorted({v.dest for v in good}):
                _print_group("výběr", dest, [v for v in good if v.dest == dest])
        elif good:
            _print_group("výběr", C.CULL_FOLDERS["good"], good)
        if unsure:
            _print_group("nejisté", C.CULL_FOLDERS["unsure"], unsure)
    else:
        print(f"  {'zůstává na místě':<30} {sum(1 for v in verdicts if not v.dest):>4}")

    if not any(v.dest for v in verdicts):
        print("Nic k přesunu.")
        return 0
    if dry_run:
        print("\n(dry run – nic se nepřesunulo)")
        return 0
    if ask and input("\nPřesunout? [A/n] ").strip().lower() not in ("", "a", "ano", "y"):
        print("Zrušeno.")
        return 0
    moved = cull.apply(folder, verdicts)
    print(f"✓ Přesunuto {moved} souborů. Vrátit jde přes: python -m fotosort cull \"{folder}\" --undo")
    return 0


def cmd_cull(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Složka neexistuje: {folder}")
        return 1
    if args.undo:
        print(f"Vráceno {cull.undo(folder)} souborů zpět do {folder}.")
        return 0
    return run_cull(folder, args.dry_run, ask=not args.yes, use_ai=not args.bez_ai, categories=args.kategorie)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fotosort")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="zkopírovat nové fotky z karty do knihovny")
    p.add_argument("--card", help="cesta ke kartě (jinak se hledá disk se složkou DCIM)")
    p.add_argument("--root", type=Path, default=LIBRARY_ROOT, help="kořen knihovny fotek")
    p.add_argument("--gap", type=int, default=DEFAULT_GAP_DAYS, help="kolik dní bez focení dělí akce")
    p.add_argument("--name", action="append", help="název akce (lze opakovat, v pořadí akcí)")
    p.add_argument("--dry-run", action="store_true", help="jen ukázat plán, nic nekopírovat")
    p.add_argument("-y", "--yes", action="store_true", help="bez dotazů, přijmout návrh")
    p.set_defaults(func=cmd_import)

    c = sub.add_parser("cull", help="roztřídit akci do _vyber / _nejiste / _ke_smazani")
    c.add_argument("folder", help="složka akce, např. ...\\_Foto\\2026\\260703-18_Norsko")
    c.add_argument("--dry-run", action="store_true", help="jen ukázat, co by se přesunulo")
    c.add_argument("--undo", action="store_true", help="vrátit poslední třídění zpět")
    c.add_argument("--bez-ai", action="store_true", help="jen technická kontrola (bez očí a AI skóre)")
    c.add_argument("--kategorie", action="store_true", help="rozdělit _vyber do podsložek podle obsahu")
    c.add_argument("-y", "--yes", action="store_true", help="bez dotazu")
    c.set_defaults(func=cmd_cull)

    args = parser.parse_args(argv)
    return args.func(args)
