"""Stažení modelů při prvním použití do %LOCALAPPDATA%\\fotosort\\models."""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

MODEL_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "fotosort" / "models"

FACE_LANDMARKER = (
    "face_landmarker.task",
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
)
AESTHETIC_MLP = (
    "laion_aesthetic_l14.pth",
    "https://github.com/christophschuhmann/improved-aesthetic-predictor/raw/main/sac%2Blogos%2Bava1-l14-linearMSE.pth",
)


def ensure(model: tuple[str, str]) -> Path:
    name, url = model
    path = MODEL_DIR / name
    if path.exists():
        return path
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Stahuji model {name} (jen poprvé)…")
    tmp = path.with_suffix(path.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, path)
    return path
