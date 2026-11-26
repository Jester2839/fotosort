from datetime import datetime
from pathlib import Path

from PIL import Image

from fotosort import cull, xmp
from fotosort.analyze import Analysis
from fotosort.media import Shot

T0 = datetime(2026, 7, 3, 10, 0, 0)
KW = [("Fotosort", "Výběr"), ("Fotosort", "Obsah", "Lidi")]


def jpg(path: Path) -> Path:
    img = Image.new("RGB", (64, 48), (120, 90, 60))
    exif = img.getexif()
    exif.get_ifd(0x8769)[0x9003] = "2026:07:03 10:00:00"
    img.save(path, "JPEG", exif=exif)
    return path


def test_raw_pair_gets_sidecar(tmp_path):
    raw, j = tmp_path / "A.ARW", jpg(tmp_path / "A.JPG")
    raw.write_bytes(b"raw")
    before = j.read_bytes()
    out = xmp.write([raw, j], 3, KW)
    assert out == tmp_path / "A.xmp"
    text = out.read_text(encoding="utf-8")
    assert 'xmp:Rating="3"' in text and "<rdf:li>Fotosort|Obsah|Lidi</rdf:li>" in text
    assert j.read_bytes() == before and raw.read_bytes() == b"raw"  # originály netknuté
    assert xmp.remove(out) and not out.exists()


def test_jpg_only_embeds_and_removes_cleanly(tmp_path):
    j = jpg(tmp_path / "B.JPG")
    before, mtime = j.read_bytes(), j.stat().st_mtime_ns
    assert xmp.write([j], 1, KW) == j
    assert xmp.is_ours(j) and j.stat().st_mtime_ns == mtime
    with Image.open(j) as img:  # pořád platný JPEG, Exif i XMP čitelné
        img.load()
        assert img.getexif().get_ifd(0x8769)[0x9003] == "2026:07:03 10:00:00"
        assert 'xmp:Rating="1"' in img.info["xmp"].decode()
    assert xmp.write([j], 3, KW) == j  # přepis vlastního
    assert xmp.remove(j) and j.read_bytes() == before


def test_foreign_xmp_is_never_overwritten(tmp_path):
    raw = tmp_path / "C.ARW"
    raw.write_bytes(b"raw")
    side = tmp_path / "C.xmp"
    side.write_text('<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core"/>')
    assert xmp.write([raw], 3, KW) is None
    assert not xmp.remove(side) and side.exists()


def test_apply_tags_keepers_moves_rejects_and_undo(tmp_path):
    folder = tmp_path / "akce"
    folder.mkdir()
    a_raw = folder / "A.ARW"
    a_raw.write_bytes(b"raw")
    a = Shot("A", [a_raw, jpg(folder / "A.JPG")], T0)
    b = Shot("B", [jpg(folder / "B.JPG")], T0)
    c = Shot("C", [jpg(folder / "C.JPG")], T0)
    vs = [cull.Verdict(s, Analysis()) for s in (a, b, c)]
    vs[0].bucket, vs[0].category = "good", "lidi"
    vs[1].bucket = "unsure"
    vs[2].reject("neostre", "test")
    before = sorted(p.name for p in folder.iterdir())
    before_b = (folder / "B.JPG").read_bytes()

    rep = cull.apply(folder, vs)
    assert (rep.moved, rep.tagged) == (1, 2)
    assert (folder / "A.xmp").exists() and xmp.is_ours(folder / "B.JPG")
    assert (folder / "_ke_smazani" / "neostre" / "C.JPG").exists()
    assert cull.is_culled(folder)

    assert cull.undo(folder) == 3
    assert sorted(p.name for p in folder.iterdir()) == before
    assert (folder / "B.JPG").read_bytes() == before_b
