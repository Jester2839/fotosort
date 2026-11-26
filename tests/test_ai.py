from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from fotosort import config as C
from fotosort import cull
from fotosort.analyze import Analysis
from fotosort.media import Shot

T0 = datetime(2026, 7, 3, 10, 0, 0)


def shot(i: int, seconds: int) -> Shot:
    return Shot(stem=f"DSC{i:05d}", files=[Path(f"DSC{i:05d}.JPG")], taken=T0 + timedelta(seconds=seconds))


def test_closed_eyes_rejected_and_series_prefers_open_eyes():
    shots = [shot(i, i * 600) for i in range(6)]              # 6 samostatných fotek
    shots += [shot(10, 4000), shot(11, 4001)]                 # série 2 snímků
    analyses = [Analysis(sharpness=500, dhash=i) for i in range(6)]
    analyses[2].eyes_closed = 0.8                             # samostatná se zavřenýma očima
    analyses += [Analysis(sharpness=900, dhash=0, eyes_closed=0.9),   # ostřejší, ale mrká
                 Analysis(sharpness=500, dhash=0, eyes_closed=0.1)]
    verdicts, n_series = cull.decide(shots, analyses)
    r = {v.shot.stem: v.reason for v in verdicts}
    assert n_series == 1
    assert r["DSC00002"] == "zavrene_oci"
    assert r["DSC00010"] == "serie" and r["DSC00011"] == ""
    assert next(v for v in verdicts if v.shot.stem == "DSC00002").dest == "_ke_smazani/zavrene_oci"


def test_assign_buckets_relative_and_categories():
    from fotosort.ai import Score, assign

    verdicts = [cull.Verdict(shot(i, i * 600), Analysis()) for i in range(10)]
    scores = [Score(float(i), "krajina" if i % 2 else "portret") for i in range(10)]
    assign(verdicts, scores, use_categories=True)
    dest = {v.shot.stem: v.dest for v in verdicts}
    # skóre 9..6 → výběr (40 %), 1..0 → slabé (20 %), zbytek nejisté
    assert dest["DSC00009"] == "_vyber/krajina"
    assert dest["DSC00008"] == "_vyber/portret"
    assert dest["DSC00006"] == "_vyber/portret"
    assert dest["DSC00005"] == "_nejiste"
    assert dest["DSC00001"] == "_ke_smazani/slabe"
    assert sum(d.startswith("_vyber") for d in dest.values()) == 4


def test_assign_small_set_never_rejects():
    from fotosort.ai import Score, assign

    verdicts = [cull.Verdict(shot(i, i * 600), Analysis()) for i in range(5)]
    assign(verdicts, [Score(5.0 + i) for i in range(5)], use_categories=False)
    assert not any(v.reason for v in verdicts)
    assert [v.dest for v in verdicts].count("_vyber") == 2


def test_apply_to_vyber_and_undo_cleans_up(tmp_path):
    from fotosort.ai import Score, assign

    folder = tmp_path / "akce"
    folder.mkdir()
    verdicts = []
    for i in range(3):
        f = folder / f"DSC{i:05d}.JPG"
        f.write_bytes(b"x")
        verdicts.append(cull.Verdict(Shot(f.stem, [f], T0), Analysis()))
    assign(verdicts, [Score(5.0, "krajina"), Score(6.0, "noc"), Score(7.0, "noc")], use_categories=True)
    assert cull.apply(folder, verdicts) == 3
    assert (folder / "_vyber" / "noc" / "DSC00002.JPG").exists()
    assert cull.undo(folder) == 3
    assert sorted(p.name for p in folder.iterdir()) == ["DSC00000.JPG", "DSC00001.JPG", "DSC00002.JPG"]


def test_assign_absolute_floors():
    from fotosort.ai import Score, assign

    good = [cull.Verdict(shot(i, i * 600), Analysis()) for i in range(10)]
    assign(good, [Score(5.0 + i / 10) for i in range(10)], use_categories=False)
    assert not any(v.reason for v in good)  # samé dobré fotky: nic do „slabé“

    weak = [cull.Verdict(shot(i, i * 600), Analysis()) for i in range(10)]
    assign(weak, [Score(3.0 + i / 10) for i in range(10)], use_categories=False)
    assert not any(v.dest.startswith("_vyber") for v in weak)  # samé slabé: nic do výběru


@pytest.mark.slow
def test_scorer_smoke_random_weights(tmp_path):
    """Ověří, že pipeline CLIP → MLP → kategorie běží (váhy jsou náhodné, čísla nedávají smysl)."""
    from fotosort import ai

    paths = []
    for i, color in enumerate([(200, 30, 30), (30, 30, 200), (90, 160, 60)]):
        p = tmp_path / f"DSC{i:05d}.JPG"
        Image.new("RGB", (900, 600), color).save(p)
        paths.append(Shot(p.stem, [p], T0))
    scorer = ai.Scorer(aesthetic_weights=None, categories={"a": ["a red photo"], "b": ["a blue photo"]},
                       pretrained=None)
    scores = ai.score_all(paths, scorer)
    assert len(scores) == 3
    assert all(isinstance(s.aesthetic, float) for s in scores)
    assert all(s.category in ("a", "b", "ostatni") for s in scores)
    # MLP musí přijmout stav ve formátu původního repozitáře
    state = {k: v.clone() for k, v in ai.AestheticMLP().state_dict().items()}
    assert set(state) == {f"layers.{i}.{t}" for i in (0, 2, 4, 6, 7) for t in ("weight", "bias")}
