"""离线欠松弛设计分析；不是生产耦合实现。"""
from __future__ import annotations
import math
from typing import Iterable, Sequence

def relaxed_sequence(raw: Sequence[float], alpha: float) -> list[float]:
    if not 0.0 < alpha <= 1.0 or any(not math.isfinite(float(v)) for v in raw):
        raise ValueError("invalid alpha or force sequence")
    out: list[float] = []
    previous = 0.0
    for value in raw:
        previous = (1.0 - alpha) * previous + alpha * float(value)
        out.append(previous)
    return out

def compare_alphas(raw: Sequence[float], alphas: Iterable[float]) -> list[dict[str, object]]:
    results = []
    for alpha in alphas:
        values = relaxed_sequence(raw, float(alpha))
        results.append({"alpha": float(alpha), "sequence": values,
                        "max_abs": max(abs(v) for v in values),
                        "sign_changes": sum(a * b < 0 for a, b in zip(values, values[1:]))})
    return results
