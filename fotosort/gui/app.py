"""Okno aplikace (pywebview). UI je v web/, tady je jen most k importer/pipeline.

Každá metoda třídy Api je z JS dostupná jako `pywebview.api.<název>()` a vrací JSON.
Dlouhé úlohy (import, třídění) běží ve vlákně a hlásí se přes `window.fs.event(...)`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import threading
import time
import traceback
from pathlib import Path

import webview

from .. import cards, cull, pipeline
from .. import config as C
from ..grouping import shooting_days, split_by_cuts, suggest_cuts
from ..importer import Event, ImportAborted, check_free_space, library_index, run_import, split_new, total_bytes
from ..media import scan_card

WEB = Path(__file__).parent / "web"
WEEKDAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]


class Cancelled(ImportAborted):
    """Uživatel klikl na Zrušit. Dědí z ImportAborted, aby kopírování uklidilo .part soubor."""


class Api:
    def __init__(self, root: Path):
        self._root = Path(root)
        self._window = None
        self._job: threading.Thread | None = None
        self._cancel = threading.Event()
        self._last_emit = 0.0
        self._scan = None  # poslední načtená karta: (card, new_shots, days)

    # --- start ------------------------------------------------------------------------------

    def init(self) -> dict:
        return {
            "root": str(self._root),
            "rootExists": self._root.is_dir(),
            "cards": self.cards(),
            "recent": self._recent(),
            "ai": importlib.util.find_spec("torch") is not None
                  and importlib.util.find_spec("open_clip") is not None,
            "lightroom": C.LIGHTROOM_EXE.exists(),
            "strictness": C.DEFAULT_STRICTNESS,
        }

    def cards(self) -> list[dict]:
        return [{"path": str(c), "label": _volume_label(c)} for c in cards.find_cards()]

    def _recent(self, limit: int = 6) -> list[dict]:
        """Naposledy změněné akce (podle složky akce a jejích přímých podsložek, ne podle názvu)."""
        if not self._root.is_dir():
            return []
        found = []
        for year in (p for p in self._root.iterdir() if p.is_dir() and p.name.isdigit()):
            for ev in (p for p in year.iterdir() if p.is_dir()):
                try:
                    mtime = max([ev.stat().st_mtime] + [c.stat().st_mtime for c in ev.iterdir() if c.is_dir()])
                except OSError:
                    continue
                found.append((mtime, ev))
        found.sort(key=lambda t: t[0], reverse=True)
        return [{"name": ev.name, "path": str(ev), "culled": cull.is_culled(ev), "modified": mtime * 1000}
                for mtime, ev in found[:limit]]

    def choose_root(self) -> dict:
        picked = self._pick_folder(self._root)
        if picked:
            self._root = Path(picked)
        return {"root": str(self._root), "recent": self._recent()}

    def choose_folder(self) -> str | None:
        return self._pick_folder(self._root)

    def _pick_folder(self, start: Path) -> str | None:
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                                 directory=str(start if start.is_dir() else Path.home()))
        return result[0] if result else None

    # --- import -----------------------------------------------------------------------------

    def scan(self, card: str) -> dict:
        try:
            shots = scan_card(Path(card))
            new, old = split_new(shots, library_index(self._root))
        except OSError as exc:
            return {"error": f"Kartu nejde přečíst: {exc}"}
        days = shooting_days(new) if new else []
        self._scan = (Path(card), new, days)
        photos = [s for s in new if not s.is_video]
        return {
            "card": card,
            "label": _volume_label(Path(card)),
            "total": len(shots),
            "photos": len(photos),
            "pairs": sum(1 for s in photos if len(s.files) > 1),
            "videos": sum(s.is_video for s in new),
            "old": len(old),
            "guessed": sum(s.time_from == "mtime" for s in new),
            "days": [{"label": f"{WEEKDAYS[d.day.weekday()]} {d.day:%d.%m.%Y}", "count": d.count} for d in days],
            "cuts": sorted(suggest_cuts(days, C.DEFAULT_GAP_DAYS)),
            "gap": C.DEFAULT_GAP_DAYS,
        }

    def _events(self, cuts: list[int], names: list[str]) -> list[Event]:
        _, new, days = self._scan
        events = [Event(g) for g in split_by_cuts(new, days, set(cuts))]
        for ev, name in zip(events, names):
            ev.name = name.strip()
        return events

    def preview(self, cuts: list[int], names: list[str]) -> dict:
        if not self._scan:
            return {"error": "Nejdřív načti kartu."}
        events = self._events(cuts, names)
        needed = total_bytes(events)
        ok, free = check_free_space(self._root, needed)
        return {
            "events": [{"prefix": Event(e.shots).path(self._root).name, "path": str(e.path(self._root)),
                        "photos": e.photo_count, "videos": e.video_count,
                        "range": _range(e)} for e in events],
            "needed": needed, "free": free, "enough": ok,
        }

    def start_import(self, cuts: list[int], names: list[str], opts: dict) -> dict:
        if not self._scan:
            return {"error": "Nejdřív načti kartu."}
        events = self._events(cuts, names)
        return self._start(self._import_job, events, opts)

    def _import_job(self, events: list[Event], opts: dict) -> None:
        self._emit(type="stage", stage="copy")
        report = run_import(events, self._root, lambda d, t, n: self._tick("copy", d, t, n))
        self._emit(type="log", msg=f"Zkopírováno {report.copied} souborů, přeskočeno {report.skipped}. "
                                   "Karta zůstala beze změny.")
        results = [self._cull_one(f, opts) if opts.get("sort") else {"folder": str(f), "name": f.name,
                                                                      "sorted": False}
                   for f in report.folders]
        self._emit(type="done", results=results, copied=report.copied, skipped=report.skipped)

    # --- třídění ----------------------------------------------------------------------------

    def start_cull(self, folder: str, opts: dict) -> dict:
        path = cull.event_folder(Path(folder))
        if not path.is_dir():
            return {"error": f"Složka neexistuje: {folder}"}
        if cull.is_culled(path):
            return {"error": "Tahle složka už je roztříděná. Nejdřív třídění vrať (Vrátit třídění), "
                             "nebo smaž _ke_smazani."}
        return self._start(lambda p, o: self._emit(type="done", results=[self._cull_one(p, o)]), path, opts)

    def _cull_one(self, folder: Path, opts: dict) -> dict:
        self._emit(type="stage", stage="analyze", folder=folder.name)
        plan = pipeline.plan_cull(folder, _Reporter(self), use_ai=opts.get("ai", True),
                                  categories=opts.get("categories", True),
                                  strictness=int(opts.get("strictness", C.DEFAULT_STRICTNESS)))
        summary = plan.summary()
        summary["sorted"] = True
        summary["keep"] = str(folder / C.PHOTO_SUBFOLDER)
        if not plan.verdicts:
            self._emit(type="log", level="warn", msg=f"{folder.name}: ve složce nejsou žádné fotky.")
            return summary
        self._emit(type="stage", stage="apply", folder=folder.name)
        rep = pipeline.apply_plan(plan)
        summary["foreign"] = len(rep.foreign_xmp)
        if rep.foreign_xmp:
            self._emit(type="log", level="warn",
                       msg=f"{len(rep.foreign_xmp)} fotek už mělo vlastní XMP – nechal jsem je být.")
        return summary

    def undo(self, folder: str) -> dict:
        try:
            return {"restored": cull.undo(Path(folder))}
        except OSError as exc:
            return {"error": f"Vrácení selhalo: {exc}"}

    def trash(self, folder: str) -> dict:
        """Přesune _ke_smazani do Koše (ne trvalé smazání)."""
        target = Path(folder) / C.CULL_FOLDERS["delete"]
        if not target.is_dir():
            return {"error": "Složka _ke_smazani neexistuje."}
        try:
            from send2trash import send2trash
        except ImportError:
            return {"error": "Chybí balíček send2trash (pip install -r requirements.txt)."}
        try:
            send2trash(str(target))
        except OSError as exc:
            return {"error": f"Přesun do Koše selhal: {exc}"}
        return {"ok": True}

    # --- ostatní ----------------------------------------------------------------------------

    def cancel(self) -> None:
        self._cancel.set()

    def open_path(self, path: str) -> dict:
        p = Path(path)
        if not p.exists():
            return {"error": f"Neexistuje: {path}"}
        try:
            os.startfile(p)  # type: ignore[attr-defined]  # jen Windows
        except AttributeError:
            subprocess.Popen(["xdg-open" if os.name == "posix" else "open", str(p)])
        return {"ok": True}

    def open_lightroom(self) -> dict:
        if not C.LIGHTROOM_EXE.exists():
            return {"error": f"Lightroom jsem nenašel v {C.LIGHTROOM_EXE} (cesta je v config.py)."}
        subprocess.Popen([str(C.LIGHTROOM_EXE)])
        return {"ok": True}

    # --- úlohy na pozadí --------------------------------------------------------------------

    def _start(self, fn, *args) -> dict:
        if self._job and self._job.is_alive():
            return {"error": "Už běží jiná úloha."}
        self._cancel.clear()

        def run():
            try:
                fn(*args)
            except Cancelled:
                self._emit(type="cancelled")
            except ImportAborted as exc:
                self._emit(type="error", msg=f"Import přerušen: {exc}. Už zkopírované soubory zůstaly, "
                                             "při dalším importu se přeskočí.")
            except Exception as exc:  # chyba nesmí zmizet potichu
                traceback.print_exc()
                self._emit(type="error", msg=f"{type(exc).__name__}: {exc}")

        self._job = threading.Thread(target=run, daemon=True)
        self._job.start()
        return {"ok": True}

    def _tick(self, stage: str, done: int, total: int, name: str) -> None:
        if self._cancel.is_set():
            raise Cancelled("zrušeno")
        now = time.monotonic()
        if done >= total or now - self._last_emit > 0.1:  # max ~10 aktualizací za sekundu
            self._last_emit = now
            self._emit(type="progress", stage=stage, done=done, total=total, name=name)

    def _emit(self, **event) -> None:
        if self._window:
            self._window.evaluate_js(f"window.fs && window.fs.event({json.dumps(event)})")


class _Reporter:
    def __init__(self, api: Api):
        self.api = api

    def log(self, msg: str, level: str = "info") -> None:
        self.api._emit(type="log", level=level, msg=msg)

    def progress(self, stage: str, done: int, total: int, name: str) -> None:
        self.api._tick(stage, done, total, name)


def _range(ev: Event) -> str:
    s, e = ev.start, ev.end
    return f"{s:%d.%m.%Y}" if s == e else f"{s:%d.%m.} – {e:%d.%m.%Y}"


def _volume_label(root: Path) -> str:
    """Jmenovka disku (Windows), jinak cesta."""
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(261)
            if ctypes.windll.kernel32.GetVolumeInformationW(str(root), buf, 261, None, None, None, None, 0):
                if buf.value:
                    return f"{buf.value} ({str(root).rstrip(chr(92))})"
        except Exception:
            pass
    return str(root)


def run(root: Path) -> int:
    api = Api(root)
    window = webview.create_window("Fotosort", url=str(WEB / "index.html"), js_api=api,
                                   width=1280, height=860, min_size=(900, 640), background_color="#111214")
    api._window = window
    webview.start()
    return 0
