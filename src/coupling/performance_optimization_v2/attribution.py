from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contracts import FACTORS, ContractError


def _median(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in ("median_wall_clock_s", "segment_wall_clock_s", "wall_clock_s"):
            if key in value:
                return float(value[key])
    return float(value)


@dataclass(frozen=True)
class AttributeResult:
    baseline_median_s: float
    final_median_s: float
    total_saving_s: float
    single_factor: dict[str, float]
    cumulative: dict[str, float]
    leave_one_out: dict[str, float]
    marginal: dict[str, float]
    normalized_weight: dict[str, float]
    interactions: dict[str, float]
    residual_overhead_s: float

    def to_dict(self) -> dict[str, Any]:
        return {"baseline_median_s": self.baseline_median_s, "final_median_s": self.final_median_s,
                "total_saving_s": self.total_saving_s, "single_factor": self.single_factor,
                "cumulative": self.cumulative, "leave_one_out": self.leave_one_out,
                "marginal": self.marginal, "normalized_weight": self.normalized_weight,
                "interactions": self.interactions, "residual_overhead_s": self.residual_overhead_s,
                "positive_weight_sum": sum(self.normalized_weight.values())}


def _key(factors: set[str]) -> str:
    return "+".join(item for item in FACTORS if item in factors) or "B"


def attribute_measurements(measurements: Mapping[str, Any]) -> AttributeResult:
    """Compute contribution only from supplied real measurements.

    No missing configuration is interpolated.  A measurement may be a scalar
    or a repeat record with ``wall_clock_s``/``segment_wall_clock_s`` values.
    """
    if "B" not in measurements or "FINAL" not in measurements:
        raise ContractError("real baseline and FINAL measurements are required")
    values: dict[str, float] = {}
    repeats: dict[str, list[float]] = {}
    for key, raw in measurements.items():
        if key in {"FINAL_FACTORS", "metadata"}:
            continue
        samples = raw if isinstance(raw, list) else [raw]
        parsed = [_median(item) for item in samples]
        if not parsed or any(item <= 0 for item in parsed):
            raise ContractError(f"invalid wall clock for {key}")
        repeats[key] = parsed; values[key] = statistics.median(parsed)
    baseline = values["B"]; final = values["FINAL"]
    final_factors = set(measurements.get("FINAL_FACTORS", FACTORS))
    final_factors.discard("FINAL")
    single = {factor: baseline - values[_key({factor})] for factor in FACTORS if _key({factor}) in values}
    cumulative = {}
    previous = baseline
    for factor in FACTORS:
        candidate = {item for item in FACTORS if FACTORS.index(item) <= FACTORS.index(factor)}
        key = _key(candidate)
        if key in values:
            cumulative[factor] = previous - values[key]
            previous = values[key]
    marginal: dict[str, float] = {}
    loo: dict[str, float] = {}
    for factor in FACTORS:
        without = set(final_factors) - {factor}
        key = _key(without)
        if key in values:
            loo[factor] = values[key]
            marginal[factor] = values[key] - final
    positive = {key: max(0.0, value) for key, value in marginal.items()}
    denom = sum(positive.values())
    weights = {key: (value / denom if denom else 0.0) for key, value in positive.items()}
    interactions: dict[str, float] = {}
    for left_index, left in enumerate(FACTORS):
        for right in FACTORS[left_index + 1:]:
            pair_key = _key({left, right})
            if pair_key in values and _key({left}) in values and _key({right}) in values:
                saving_pair = baseline - values[pair_key]
                interactions[f"{left}+{right}"] = saving_pair - single[left] - single[right]
    explained = sum(marginal.values())
    return AttributeResult(baseline, final, baseline - final, single, cumulative, loo, marginal, weights,
                           interactions, (baseline - final) - explained)


def load_and_attribute(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return attribute_measurements(value).to_dict()
