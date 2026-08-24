from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from ..stage4f_three_slice_timestep_diagnostic_v3.engine_impl import DiagnosticEngine
from .contract import FORCE_ABSOLUTE_SCALE_N, MAX_ITERATIONS, RELAXATION_CANDIDATES, TARGET_TIME_S


def _norm(rows: Sequence[Sequence[float]]) -> float:
    return max(abs(float(value)) for row in rows for value in row)


def _difference(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> float:
    return max(abs(float(x) - float(y)) for ra, rb in zip(a, b) for x, y in zip(ra, rb))


def _relax(old: Sequence[Sequence[float]], observed: Sequence[Sequence[float]], alpha: float) -> list[list[float]]:
    return [[(1.0-alpha)*float(x) + alpha*float(y) for x, y in zip(ro, rn)] for ro, rn in zip(old, observed)]


def run(*, root: Path, parent: Path) -> dict[str, Any]:
    parent_payload = json.loads(parent.read_text(encoding="utf-8"))
    initial = [[float(v) for v in row] for row in parent_payload["previous_slice_forces_N"]]
    candidates = []
    for alpha in RELAXATION_CANDIDATES:
        current = [row[:] for row in initial]
        iterations = []
        for index in range(MAX_ITERATIONS):
            iteration_root = root / f"alpha_{alpha:.2f}" / f"iteration_{index:02d}"
            plan = {"branch": "D2", "dt_s": 0.000625, "case_root": str(iteration_root.resolve()),
                    "source_checkpoint": str(parent.resolve())}
            engine = DiagnosticEngine(plan)
            try:
                engine.scheduler.previous_slice_forces_N = [row[:] for row in current]
                row = dict(engine(0, TARGET_TIME_S))
            finally:
                engine.shutdown()
            observed = [list(item["integrated_slice_force_N"]) for item in row["force_audit"]]
            residual_abs = _difference(observed, current)
            residual_rel = residual_abs / max(FORCE_ABSOLUTE_SCALE_N, _norm(current), _norm(observed))
            updated = _relax(current, observed, alpha)
            iterations.append({"iteration": index, "input_force_N": current, "observed_force_N": observed,
                "relaxed_force_N": updated, "force_residual_abs_N": residual_abs,
                "force_residual_relative": residual_rel, "max_abs_Cd": row["max_abs_Cd"],
                "max_cfl": row["max_cfl"], "position_difference_over_D": row["position_difference_over_D"],
                "velocity_difference_over_U": row["velocity_difference_over_U"],
                "virtual_work_relative_error": row["virtual_work_relative_error"],
                "force_conversion_relative_error": row["force_conversion_relative_error"],
                "checkpoint": row["checkpoint"], "checkpoint_sha256": row["checkpoint_sha256"],
                "log_passed": row["log_passed"]})
            current = updated
        residuals = [row["force_residual_relative"] for row in iterations]
        contractions = [b/a for a,b in zip(residuals,residuals[1:]) if a > 0]
        candidates.append({"alpha": alpha, "iterations": iterations, "residuals": residuals,
            "contraction_factors": contractions,
            "contracting": bool(contractions) and all(math.isfinite(v) and v < 1.0 for v in contractions)})
    result = {"schema": "stage4f-c-fixed-point-diagnostic-v1-result-1.0.0",
        "parent_checkpoint": str(parent.resolve()), "parent_checkpoint_sha256": sha256_file(parent),
        "target_time_s": TARGET_TIME_S, "candidates": candidates,
        "production_gate_claim": False, "physical_steps_committed_to_mainline": 0}
    atomic_write_json(root / "fixed_point_diagnostic_result.json", result)
    return result

