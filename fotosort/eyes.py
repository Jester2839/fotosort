"""Zavřené oči přes MediaPipe Face Landmarker (blendshapes eyeBlinkLeft/Right).

Běží v pracovních procesech analýzy; landmarker se vytvoří jednou na proces.
"""

from __future__ import annotations

import numpy as np

from . import config as C

_landmarker = None
_model_path: str | None = None


def _get(model_path: str):
    global _landmarker, _model_path
    if _landmarker is None or _model_path != model_path:
        import mediapipe as mp  # noqa: F401  (import až tady: hlavní proces ho nepotřebuje)
        from mediapipe.tasks.python import BaseOptions, vision

        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.IMAGE,
            output_face_blendshapes=True,
            num_faces=8,
        )
        _landmarker = vision.FaceLandmarker.create_from_options(options)
        _model_path = model_path
    return _landmarker


def _blink(shapes, name: str, index: int) -> float:
    for c in shapes:
        if (c.category_name or "").lower() == name.lower():
            return float(c.score)
    return float(shapes[index].score) if len(shapes) > index else 0.0


def closed_eyes_score(rgb: np.ndarray, model_path: str) -> float:
    """Nejvyšší „zavřenost“ (min. z obou očí) mezi výraznými obličeji. -1 = žádný obličej."""
    import mediapipe as mp

    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    result = _get(model_path).detect(image)
    worst = -1.0
    for landmarks, shapes in zip(result.face_landmarks, result.face_blendshapes or []):
        xs = [p.x for p in landmarks]
        if max(xs) - min(xs) < C.FACE_MIN_WIDTH:
            continue
        both = min(_blink(shapes, "eyeBlinkLeft", 9), _blink(shapes, "eyeBlinkRight", 10))
        worst = max(worst, both)
    return worst
