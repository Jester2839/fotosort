"""Rozdělení snímků na akce podle dnů bez focení (ne podle hodinových mezer)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from .media import Shot


@dataclass
class Day:
    day: date
    count: int


def shooting_days(shots: list[Shot]) -> list[Day]:
    counts = Counter(s.taken.date() for s in shots)
    return [Day(d, counts[d]) for d in sorted(counts)]


def suggest_cuts(days: list[Day], gap_days: int) -> set[int]:
    """Vrátí indexy dnů, kterými začíná nová akce.

    Řez se navrhne, když mezi dvěma dny s fotkami je aspoň `gap_days` celých dnů bez fotek.
    """
    cuts = set()
    for i in range(1, len(days)):
        empty_between = (days[i].day - days[i - 1].day).days - 1
        if empty_between >= gap_days:
            cuts.add(i)
    return cuts


def split_by_cuts(shots: list[Shot], days: list[Day], cuts: set[int]) -> list[list[Shot]]:
    """Rozdělí snímky do skupin; `cuts` jsou indexy do `days`."""
    starts = sorted({days[i].day for i in cuts if 0 < i < len(days)})
    groups: list[list[Shot]] = [[] for _ in range(len(starts) + 1)]
    for shot in sorted(shots, key=lambda s: s.taken):
        idx = sum(1 for d in starts if shot.taken.date() >= d)
        groups[idx].append(shot)
    return [g for g in groups if g]
