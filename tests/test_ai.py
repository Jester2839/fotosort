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
    verdicts = [cull.Verdict(shot(i, i * 600), Analysis()) for i in range(10)]
    scores = [cull.Score(float(i), "zvirata" if i % 2 else "lidi") for i in range(10)]
    cull.assign(verdicts, scores, use_categories=True)
    by = {v.shot.stem: v for v in verdicts}
    # skóre 9..6 → výběr (40 %), 1..0 → slabé (20 %), zbytek nejisté
    assert by["DSC00009"].bucket == "good" and by["DSC00009"].category == "zvirata"
    assert by["DSC00006"].bucket == "good" and not by["DSC00006"].dest  # výběr zůstává na místě
    assert by["DSC00005"].bucket == "unsure"
    assert by["DSC00001"].dest == "_ke_smazani/slabe"
    assert sum(v.bucket == "good" for v in verdicts) == 4
    assert cull.keywords_for(by["DSC00009"]) == [("Fotosort", "Výběr"), ("Fotosort", "Obsah", "Zvířata")]


def test_assign_strictness():
    def run(level):
        vs = [cull.Verdict(shot(i, i * 600), Analysis()) for i in range(10)]
        cull.assign(vs, [cull.Score(float(i)) for i in range(10)], use_categories=False, strictness=level)
        return sum(v.bucket == "good" for v in vs), sum(v.reason == "slabe" for v in vs)

    assert run(1) == (4, 0)  # mírná: AI nic nevyhazuje
    assert run(2) == (4, 2)
    assert run(3) == (3, 3)


def test_assign_small_set_never_rejects():
    verdicts = [cull.Verdict(shot(i, i * 600), Analysis()) for i in range(5)]
    cull.assign(verdicts, [cull.Score(5.0 + i) for i in range(5)], use_categories=False)
    assert not any(v.reason for v in verdicts)
    assert [v.bucket for v in verdicts].count("good") == 2


def test_assign_absolute_floors():
    good = [cull.Verdict(shot(i, i * 600), Analysis()) for i in range(10)]
    cull.assign(good, [cull.Score(5.0 + i / 10) for i in range(10)], use_categories=False)
    assert not any(v.reason for v in good)  # samé dobré fotky: nic do „slabé“

    weak = [cull.Verdict(shot(i, i * 600), Analysis()) for i in range(10)]
    cull.assign(weak, [cull.Score(3.0 + i / 10) for i in range(10)], use_categories=False)
    assert not any(v.bucket == "good" for v in weak)  # samé slabé: nic do výběru


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
