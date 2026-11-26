from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter

from fotosort import cull
from fotosort.cli import main

T0 = datetime(2026, 7, 3, 10, 0, 0)


def scene(seed: int) -> Image.Image:
    """Texturovaná „fotka“: obdélníky různých jasů + jemný šum."""
    rng = np.random.default_rng(seed)
    arr = np.full((800, 1200), 110, dtype=np.float32)
    for _ in range(40):
        y, x = rng.integers(0, 700), rng.integers(0, 1100)
        arr[y:y + rng.integers(20, 120), x:x + rng.integers(20, 120)] = rng.integers(30, 220)
    arr += rng.normal(0, 6, arr.shape)
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8)).convert("RGB")


def save(folder: Path, name: str, img: Image.Image, taken: datetime, raw: bool = False) -> None:
    exif = img.getexif()
    exif.get_ifd(0x8769)[0x9003] = taken.strftime("%Y:%m:%d %H:%M:%S")
    img.save(folder / f"{name}.JPG", "JPEG", quality=92, exif=exif)
    if raw:
        (folder / f"{name}.ARW").write_bytes(b"fake raw")


@pytest.fixture
def event(tmp_path):
    f = tmp_path / "260703_test"
    f.mkdir()
    # 8 různých ostrých scén, minutu od sebe
    for i in range(8):
        save(f, f"DSC{i:05d}", scene(i), T0 + timedelta(minutes=i), raw=(i == 0))
    # neostrá fotka (RAW+JPG, musí se přesunout obě)
    save(f, "DSC00100", scene(100).filter(ImageFilter.GaussianBlur(10)), T0 + timedelta(minutes=30), raw=True)
    # série 4 snímků po 1 s, nejostřejší je DSC00202
    for j, radius in enumerate([1.5, 1.0, 0, 2.0]):
        img = scene(200)
        if radius:
            img = img.filter(ImageFilter.GaussianBlur(radius))
        save(f, f"DSC{200 + j:05d}", img, T0 + timedelta(minutes=40, seconds=j))
    # přepálené samotné JPG
    save(f, "DSC00300", Image.new("RGB", (1200, 800), (255, 255, 255)), T0 + timedelta(minutes=50))
    # podsložky se neprochází
    (f / "_upraveno").mkdir()
    save(f / "_upraveno", "upravena", scene(1).filter(ImageFilter.GaussianBlur(10)), T0)
    return f


def reasons(folder):
    shots = cull.find_shots(folder)
    verdicts, n_series = cull.decide(shots, cull.analyze_all(shots, workers=2))
    return {v.shot.stem: v.reason for v in verdicts}, n_series


def test_decisions(event):
    r, n_series = reasons(event)
    assert n_series == 1
    assert r["DSC00100"] == "neostre"
    assert r["DSC00202"] == ""
    assert {r[f"DSC{n:05d}"] for n in (200, 201, 203)} == {"serie"}
    assert r["DSC00300"] in ("expozice", "neostre")  # bílá plocha je i bez detailu
    assert all(r[f"DSC{i:05d}"] == "" for i in range(8))
    assert "upravena" not in r


def test_apply_moves_pairs_and_undo_restores(event):
    before = sorted(p.name for p in event.iterdir() if p.is_file())
    assert main(["cull", str(event), "-y", "--bez-ai"]) == 0

    trash = event / "_ke_smazani"
    assert (trash / "neostre" / "DSC00100.JPG").exists()
    assert (trash / "neostre" / "DSC00100.ARW").exists()
    assert (trash / "serie" / "DSC00200.JPG").exists()
    assert (event / "DSC00202.JPG").exists()
    assert (event / "DSC00000.ARW").exists()

    assert main(["cull", str(event), "--undo"]) == 0
    after = sorted(p.name for p in event.iterdir() if p.is_file())
    assert after == before
    assert not trash.exists()


def test_dry_run_moves_nothing(event):
    before = sorted(p.name for p in event.iterdir())
    assert main(["cull", str(event), "--dry-run", "--bez-ai"]) == 0
    assert sorted(p.name for p in event.iterdir()) == before
