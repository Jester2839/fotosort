from datetime import date, datetime

import pytest

from fotosort.cli import main
from fotosort.grouping import shooting_days, split_by_cuts, suggest_cuts
from fotosort.media import scan_card
from fotosort.naming import date_range_label, event_folder_name

from .fake_card import add_photo, add_video


@pytest.mark.parametrize("start,end,expected", [
    (date(2026, 8, 12), date(2026, 8, 12), "260812"),
    (date(2026, 8, 13), date(2026, 8, 16), "260813-16"),
    (date(2026, 7, 30), date(2026, 8, 2), "260730-0802"),
    (date(2025, 12, 30), date(2026, 1, 2), "251230-260102"),
])
def test_date_range_label(start, end, expected):
    assert date_range_label(start, end) == expected


def test_folder_name_strips_windows_chars():
    assert event_folder_name(date(2026, 5, 1), date(2026, 5, 3), 'Machov: "výlet"?') == "260501-03_Machov výlet"
    assert event_folder_name(date(2026, 5, 1), date(2026, 5, 1), "  ") == "260501"


@pytest.fixture
def card(tmp_path):
    c = tmp_path / "card"
    # Dovolená 3.–6.7. s jedním dnem pauzy (5.7.), pak o 10 dní později jednodenní akce.
    add_photo(c, 1, datetime(2026, 7, 3, 9, 0))                      # RAW+JPG
    add_photo(c, 2, datetime(2026, 7, 3, 23, 59), jpg=False)         # jen RAW
    add_photo(c, 3, datetime(2026, 7, 4, 0, 30), raw=False)          # jen JPG, po půlnoci
    add_photo(c, 4, datetime(2026, 7, 6, 18, 0))
    add_video(c, 1, datetime(2026, 7, 4, 12, 0))
    add_photo(c, 5, datetime(2026, 7, 16, 10, 0))
    return c


def test_scan_pairs_raw_and_jpg(card):
    shots = scan_card(card)
    photos = [s for s in shots if not s.is_video]
    assert len(photos) == 5
    assert sorted(len(s.files) for s in photos) == [1, 1, 2, 2, 2]
    assert all(s.time_from in ("exif", "xml") for s in shots)


def test_one_day_pause_does_not_split_trip(card):
    shots = scan_card(card)
    days = shooting_days(shots)
    cuts = suggest_cuts(days, gap_days=2)
    groups = split_by_cuts(shots, days, cuts)
    assert [len(g) for g in groups] == [5, 1]  # 4 fotky + video | 1 fotka


def test_full_import_and_reimport(card, tmp_path, capsys):
    root = tmp_path / "_Foto"
    assert main(["import", "--card", str(card), "--root", str(root), "-y",
                 "--name", "Norsko", "--name", "zatmeni slunce"]) == 0

    trip = root / "2026" / "260703-06_Norsko"
    assert not [p for p in trip.iterdir() if p.is_file()]  # fotky jdou do _vyber, ne do kořene akce
    assert sorted(p.name for p in (trip / "_vyber").iterdir()) == [
        "260703_090000_DSC00001.ARW", "260703_090000_DSC00001.JPG",
        "260703_235900_DSC00002.ARW", "260704_003000_DSC00003.JPG",
        "260706_180000_DSC00004.ARW", "260706_180000_DSC00004.JPG",
    ]
    assert (trip / "_upraveno").is_dir()
    assert (trip / "video" / "260704_120000_C0001.MP4").exists()
    assert (root / "2026" / "260716_zatmeni slunce" / "_vyber" / "260716_100000_DSC00005.JPG").exists()
    assert not list(root.rglob("*.part"))

    # Druhé vložení stejné karty: nic nového.
    capsys.readouterr()
    assert main(["import", "--card", str(card), "--root", str(root), "-y"]) == 0
    assert "už je importované" in capsys.readouterr().out

    # Na kartu přibude nová fotka: importuje se jen ona.
    add_photo(card, 6, datetime(2026, 8, 1, 8, 0))
    assert main(["import", "--card", str(card), "--root", str(root), "-y", "--name", "tabor"]) == 0
    assert (root / "2026" / "260801_tabor" / "_vyber" / "260801_080000_DSC00006.ARW").exists()


def test_dry_run_writes_nothing(card, tmp_path):
    root = tmp_path / "_Foto"
    assert main(["import", "--card", str(card), "--root", str(root), "-y", "--dry-run"]) == 0
    assert not root.exists()
