"""Serial real-process runner for the predictor-consistent three-step preflight."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from ..stage4f_c_strong_coupling_preflight_v1.coordinator import (
    DT_TICK_NS,
    START_TIME_TICK_NS,
)
from .contract import (
    ALPHA,
    CONSECUTIVE_CONVERGED_ITERATIONS,
    FORCE_CONVERSION_RELATIVE_ERROR_MAX,
    FORCE_RESIDUAL_ABSOLUTE_MAX_N,
    FORCE_RESIDUAL_RELATIVE_MAX,
    FORCE_RESIDUAL_RELATIVE_SCALE_N,
    MAX_ABS_CD,
    MAX_CFL_EXCLUSIVE,
    MAX_ITERATIONS,
    POSITION_DIFFERENCE_OVER_D_MAX,
    VELOCITY_DIFFERENCE_OVER_U_MAX,
    VIRTUAL_WORK_RELATIVE_ERROR_MAX,
    build_contract,
    validate_contract,
)
from .iteration_engine import CandidateIterationEngine

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PARENT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_fixed_point_v5" / "formal_preflight_attempt3" / "checkpoints" / "checkpoint_step00000002_d4def62051c1.json"
DEFAULT_CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_c_predictor_consistent_strong_v2_attempt1"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "results" / "15_stage4f_c_predictor_consistent_strong_v2_attempt1"


def _force(rows: Sequence[Sequence[float]]) -> list[list[float]]:
    value = [[float(component) for component in row] for row in rows]
    if len(value) != 3 or any(len(row) != 3 for row in value):
        raise RuntimeError("force matrix must be 3 x 3")
    if not all(math.isfinite(component) for row in value for component in row):
        raise RuntimeError("force matrix contains NaN/Inf")
    return value


def _residual(observed: Sequence[Sequence[float]], relaxed: Sequence[Sequence[float]]) -> tuple[float, float]:
    absolute = max(abs(float(a) - float(b)) for ra, rb in zip(observed, relaxed) for a, b in zip(ra, rb))
    norm = max(abs(float(value)) for row in list(observed) + list(relaxed) for value in row)
    return absolute, absolute / max(FORCE_RESIDUAL_RELATIVE_SCALE_N, norm)


def _relax(old: Sequence[Sequence[float]], observed: Sequence[Sequence[float]]) -> list[list[float]]:
    return [[(1.0 - ALPHA) * float(a) + ALPHA * float(b) for a, b in zip(ra, rb)] for ra, rb in zip(old, observed)]


def _safety_failure(row: dict[str, Any]) -> str | None:
    checks = {
        "max_cfl": float(row["max_cfl"]),
        "position": float(row["position_difference_over_D"]),
        "velocity": float(row["velocity_difference_over_U"]),
        "virtual_work": float(row["virtual_work_relative_error"]),
        "force_conversion": float(row["force_conversion_relative_error"]),
        "Cd": float(row["max_abs_Cd"]),
    }
    if not all(math.isfinite(value) and value >= 0.0 for value in checks.values()): return "nonfinite_or_negative_metric"
    if checks["max_cfl"] >= MAX_CFL_EXCLUSIVE: return "CFL_gate"
    if checks["position"] > POSITION_DIFFERENCE_OVER_D_MAX: return "position_gate"
    if checks["velocity"] > VELOCITY_DIFFERENCE_OVER_U_MAX: return "velocity_gate"
    if checks["virtual_work"] > VIRTUAL_WORK_RELATIVE_ERROR_MAX: return "virtual_work_gate"
    if checks["force_conversion"] > FORCE_CONVERSION_RELATIVE_ERROR_MAX: return "force_conversion_gate"
    if not row.get("all_three_slices_complete") or not row.get("log_audit", {}).get("passed"): return "slice_or_log_gate"
    if row.get("state_coherence_audit", {}).get("status") != "passed": return "predictor_state_coherence_gate"
    return None


def _collect_processes(case_root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    registries = list(case_root.rglob("owned_process_registry.json")) if case_root.exists() else []
    for path in registries:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list): rows.extend(payload)
    return {
        "registry_count": len(registries), "started": len(rows),
        "closed": sum(item.get("end_timestamp") is not None for item in rows),
        "residual": sum(item.get("end_timestamp") is None for item in rows),
        "nonzero_return_codes": sum(item.get("return_code") not in (None, 0) for item in rows),
        "maximum_live_candidate_engines": 1,
    }


def run_three_step(*, parent_checkpoint: Path, case_root: Path, result_root: Path) -> dict[str, Any]:
    parent_checkpoint, case_root, result_root = parent_checkpoint.resolve(), case_root.resolve(), result_root.resolve()
    if case_root.exists() or (result_root.exists() and any(result_root.iterdir())):
        raise FileExistsError("v2 real-run roots must be new and empty")
    result_root.mkdir(parents=True)
    parent_sha = sha256_file(parent_checkpoint)
    parent_payload = json.loads(parent_checkpoint.read_text(encoding="utf-8"))
    contract = build_contract(parent_sha); validate_contract(contract)
    atomic_write_json(result_root / "predictor_consistent_contract.json", contract)
    previous_force = _force(parent_payload["previous_slice_forces_N"])
    current_parent = parent_checkpoint
    current_parent_sha = parent_sha
    steps: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None

    for physical_step in range(3):
        current_tick = START_TIME_TICK_NS + physical_step * DT_TICK_NS
        target_tick = current_tick + DT_TICK_NS
        relaxed = _force(previous_force); streak = 0
        step_row: dict[str, Any] = {"physical_step": physical_step, "current_tick_ns": current_tick,
            "target_tick_ns": target_tick, "parent_checkpoint": str(current_parent),
            "parent_checkpoint_sha256": current_parent_sha, "iterations": [], "status": "running"}
        steps.append(step_row)
        for iteration in range(MAX_ITERATIONS):
            root = case_root / f"step_{physical_step:02d}" / f"iteration_{iteration:02d}"
            plan = {"branch": "predictor_consistent_v2", "dt_s": DT_TICK_NS / 1e9,
                "physical_step": physical_step, "current_time_s": current_tick / 1e9,
                "target_time_s": target_tick / 1e9, "case_root": str(root),
                "source_checkpoint": str(current_parent)}
            engine = None
            try:
                engine = CandidateIterationEngine(plan)
                evidence = dict(engine.run_trial(previous_slice_forces_N=relaxed))
                observed = _force(evidence["observed_slice_forces_N"])
                absolute, relative = _residual(observed, relaxed)
                safety = _safety_failure(evidence)
                residual_ok = absolute <= FORCE_RESIDUAL_ABSOLUTE_MAX_N and relative <= FORCE_RESIDUAL_RELATIVE_MAX
                streak = streak + 1 if residual_ok else 0
                final_candidate = streak >= CONSECUTIVE_CONVERGED_ITERATIONS
                cd_ok = float(evidence["max_abs_Cd"]) <= MAX_ABS_CD
                item = {"strong_iteration": iteration, "relaxed_force_N": relaxed,
                    "observed_force_N": observed, "force_residual_absolute_N": absolute,
                    "force_residual_relative": relative, "residual_consecutive_count": streak,
                    "max_abs_Cd": evidence["max_abs_Cd"], "max_cfl": evidence["max_cfl"],
                    "position_difference_over_D": evidence["position_difference_over_D"],
                    "velocity_difference_over_U": evidence["velocity_difference_over_U"],
                    "predictor_state_sha256": evidence["predictor_snapshot"]["state_sha256"],
                    "published_motion_sha256": evidence["predictor_snapshot"]["published_motion_sha256"],
                    "safety_failure": safety, "final_candidate": final_candidate,
                    "final_Cd_acceptance": cd_ok if final_candidate else None}
                step_row["iterations"].append(item)
                atomic_write_json(result_root / "execution_progress.json", {"steps": steps, "failure": failure})
                if safety:
                    failure = {"physical_step": physical_step, "strong_iteration": iteration, "reason": safety}
                    engine.discard_trial(); step_row["status"] = "failed_hard_gate"; break
                if final_candidate and cd_ok:
                    checkpoint = engine.promote()
                    checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
                    structure_path = Path(checkpoint).parent / checkpoint_payload["structure"]["checkpoint_relative_path"]
                    if checkpoint_payload["structure"]["checkpoint_sha256"] != sha256_file(structure_path):
                        raise RuntimeError("promoted predictor structure checkpoint hash mismatch")
                    step_row.update(status="committed", selected_iteration=iteration,
                        checkpoint=str(checkpoint), checkpoint_sha256=sha256_file(checkpoint))
                    current_parent, current_parent_sha = Path(checkpoint), sha256_file(checkpoint)
                    previous_force = observed
                    break
                engine.discard_trial()
                relaxed = _relax(relaxed, observed)
            except Exception as exc:
                failure = {"physical_step": physical_step, "strong_iteration": iteration,
                    "reason": f"{type(exc).__name__}: {exc}"}
                step_row["status"] = "failed_exception"
                break
            finally:
                if engine is not None: engine.shutdown()
        if step_row["status"] == "running":
            step_row["status"] = "failed_iteration_limit"
            failure = {"physical_step": physical_step, "strong_iteration": MAX_ITERATIONS - 1,
                "reason": "iteration_limit_without_final_Cd_acceptance"}
        if step_row["status"] != "committed": break

    processes = _collect_processes(case_root)
    summary = {"schema": "stage4f-c-predictor-consistent-strong-v2-result-1.0.0",
        "status": "passed" if len(steps) == 3 and all(row["status"] == "committed" for row in steps) else "failed",
        "contract_sha256": contract["contract_sha256"], "parent_checkpoint": str(parent_checkpoint),
        "parent_checkpoint_sha256": parent_sha, "requested_physical_steps": 3,
        "committed_physical_steps": sum(row["status"] == "committed" for row in steps),
        "steps": steps, "first_failure": failure, "processes": processes}
    atomic_write_json(result_root / "real_execution_summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true")
    parser.add_argument("--parent", default=str(DEFAULT_PARENT)); parser.add_argument("--case-root", default=str(DEFAULT_CASE_ROOT)); parser.add_argument("--result-root", default=str(DEFAULT_RESULT_ROOT))
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "not_executed", "reason": "--execute required"}, indent=2)); return 0
    print(json.dumps(run_three_step(parent_checkpoint=Path(args.parent), case_root=Path(args.case_root), result_root=Path(args.result_root)), ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
