from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from .contracts import FACTORS


@dataclass(frozen=True)
class MatrixEntry:
    label: str
    factors: tuple[str, ...]
    steps: int = 40


def required_matrix() -> tuple[MatrixEntry, ...]:
    entries = [MatrixEntry("B", ())]
    entries.extend(MatrixEntry(factor, (factor,)) for factor in FACTORS)
    entries.extend(MatrixEntry("+".join(pair), pair) for pair in (("M", "O"), ("M", "P"), ("M", "O", "P"),
                                                                    ("M", "O", "P", "I"), ("M", "O", "P", "I", "A")))
    entries.append(MatrixEntry("FINAL", FACTORS))
    return tuple(entries)


def validate_matrix(labels: Iterable[str]) -> None:
    expected = {entry.label for entry in required_matrix()}
    actual = set(labels)
    missing = expected - actual
    if missing:
        raise ValueError("required benchmark configurations missing: " + ",".join(sorted(missing)))
