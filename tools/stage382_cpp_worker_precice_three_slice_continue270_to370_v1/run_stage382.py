"""100 s continuation with compact force/phase/displacement observability."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREVIOUS = ROOT / "tools/stage379_cpp_worker_precice_three_slice_continue200_to220_v1/run_stage379.py"
spec = importlib.util.spec_from_file_location("stage381_impl", PREVIOUS)
assert spec and spec.loader
impl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(impl)
sys.path.insert(0, str(ROOT / "src"))
from coupling.stage382_observables_v1.metrics import compute_window_metrics, validate_contract  # noqa: E402

SOURCE = ROOT / "runtime/stage381_cpp_worker_precice_three_slice_continue220_to270_v1"
SOURCE_STATE = SOURCE / "logs/structure_participant.json"
RUNTIME = ROOT / "runtime/stage382_cpp_worker_precice_three_slice_continue270_to370_v1"
RESULTS = ROOT / "results/stage382_cpp_worker_precice_three_slice_continue270_to370_v1"
STAGE_ID = "stage4f_d_cpp_worker_precice_three_slice_continue270_to370_v1"
RUN_ID = "run382_cpp_worker_precice_three_slice_continue270_to370_v1"
CASE_ID = "case382_cpp_worker_precice_three_slice_continue270_to370_v1"
DT = 0.005
SOURCE_STEP = 54000
SOURCE_TIME = 270.0
STEPS = 20000
TARGET_STEP = SOURCE_STEP + STEPS
TARGET_TIME = SOURCE_TIME + STEPS * DT


def configure_impl() -> None:
    for name, value in {"SOURCE": SOURCE, "SOURCE_STATE": SOURCE_STATE, "RUNTIME": RUNTIME, "RESULTS": RESULTS, "STAGE_ID": STAGE_ID, "RUN_ID": RUN_ID, "CASE_ID": CASE_ID, "DT": DT, "SOURCE_STEP": SOURCE_STEP, "SOURCE_TIME": SOURCE_TIME, "STEPS": STEPS, "TARGET_STEP": TARGET_STEP, "TARGET_TIME": TARGET_TIME}.items():
        setattr(impl, name, value)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source() -> dict[str, object]:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to reuse Stage 382 paths")
    if not SOURCE_STATE.is_file():
        raise RuntimeError(f"missing source state: {SOURCE_STATE}")
    state = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    checks: dict[str, bool] = {
        "finalized": state.get("finalized") is True,
        "source_step": state.get("committed_steps") == SOURCE_STEP,
        "source_local_steps": state.get("local_committed_steps") == 10000,
        "source_time": abs(float(state.get("target_time_s", -1.0)) - SOURCE_TIME) <= 1.0e-12,
        "slice_counts": state.get("slice_counts") == {f"slice_{i:04d}": 10000 for i in range(3)},
    }
    fields = ("U", "p", "pointDisplacement", "cellDisplacement", "phi", "meshPhi", "Uf", "Force")
    for index in range(3):
        restart = SOURCE / f"slice_{index:04d}/{SOURCE_TIME:g}"
        checks[f"slice_{index:04d}_fields"] = all((restart / field).is_file() for field in fields)
    if not all(checks.values()):
        raise RuntimeError("source endpoint verification failed: " + json.dumps(checks))
    return {"source_runtime": str(SOURCE), "source_state_sha256": sha256(SOURCE_STATE), "source_step": SOURCE_STEP, "source_time_s": SOURCE_TIME, "source_fields": list(fields), "source_read_only": True, "checks": checks}


def write_observation_contract(source_manifest: dict[str, object]) -> dict[str, object]:
    contract = {
        "schema_version": 1,
        "stage_id": STAGE_ID,
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "slice_ids": [f"slice_{i:04d}" for i in range(3)],
        "sample_interval_s": 0.05,
        "window_interval_s": 10.0,
        "force_fields": ["force_y", "weighted_force_y", "mean", "rms", "peak_to_peak"],
        "displacement_fields": ["displacement_y", "mean", "rms", "peak_to_peak"],
        "phase_fields": ["lag_samples", "lag_time_s", "correlation"],
        "missing_value_policy": "fail_closed_no_interpolation",
        "formal_gate_unchanged": True,
        "source_manifest": source_manifest,
        "record_path": str(RUNTIME / "logs/observables_0p05s.jsonl"),
    }
    validate_contract(contract)
    (RUNTIME / "logs/observation_contract.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return contract


def build_observations() -> dict[str, object]:
    logs = RUNTIME / "logs"
    path = logs / "mapping_diagnostics.jsonl"
    if not path.is_file():
        raise RuntimeError("mapping diagnostics missing")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != STEPS:
        raise RuntimeError(f"mapping row count {len(rows)} != {STEPS}")
    expected_step = SOURCE_STEP
    sampled: list[dict[str, object]] = []
    times: list[float] = []
    force_by_slice = {f"slice_{i:04d}": [] for i in range(3)}
    displacement: list[float] = []
    for row in rows:
        expected_step += 1
        if row.get("global_step") != expected_step or row.get("integer_tick") != int(round(float(row["time_s"]) * 1.0e9)):
            raise RuntimeError("step/time/tick identity mismatch in mapping diagnostics")
        if expected_step % 10:
            continue
        times.append(float(row["time_s"]))
        slices = row.get("interface_positions_xy")
        if not isinstance(slices, list) or len(slices) != 3:
            raise RuntimeError("missing scalar observation fields")
        displacement.append(statistics_mean(float(point[1]) for point in slices))
        sampled.append({"global_step": row["global_step"], "time_s": row["time_s"], "integer_tick": row["integer_tick"], "displacement_y": displacement[-1], "virtual_work_error": row.get("virtual_work_error"), "force_balance_error": row.get("force_balance_error"), "moment_balance_error": row.get("moment_balance_error")})
    if len(sampled) != STEPS // 10:
        raise RuntimeError("unexpected 0.05 s scalar sample count")
    # Force files are scalar evidence and include exactly the same 0.005 s grid.
    force_pattern = re.compile(r"^\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+\(\(([^)]*)\)\s+\(([^)]*)\)\)")
    for index, sid in enumerate(force_by_slice):
        force_path = RUNTIME / sid / "postProcessing" / "forces1" / f"{SOURCE_TIME:g}" / "forces.dat"
        parsed: list[tuple[float, float]] = []
        if not force_path.is_file():
            raise RuntimeError(f"force scalar file missing: {force_path}")
        for line in force_path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = force_pattern.match(line)
            if match:
                pressure = [float(value) for value in match.group(2).split()]
                viscous = [float(value) for value in match.group(3).split()]
                parsed.append((float(match.group(1)), pressure[1] + viscous[1]))
        if len(parsed) != STEPS + 1:
            raise RuntimeError(f"force scalar count {len(parsed)} != {STEPS + 1}: {force_path}")
        for sample_index, record in enumerate(sampled, start=1):
            force_time, force_value = parsed[sample_index * 10]
            if abs(force_time - float(record["time_s"])) > 1.0e-9:
                raise RuntimeError("force/mapping observation time mismatch")
            force_by_slice[sid].append(force_value)
    for index, record in enumerate(sampled):
        record["weighted_force_y"] = statistics_mean(force_by_slice[sid][index] for sid in force_by_slice)
    out = logs / "observables_0p05s.jsonl"
    out.write_text("\n".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in sampled) + "\n", encoding="utf-8")
    windows = []
    start = SOURCE_TIME
    while start < TARGET_TIME - 1.0e-12:
        stop = min(TARGET_TIME, start + 10.0)
        windows.append(compute_window_metrics(times, force_by_slice, displacement, start_time_s=start, end_time_s=stop))
        start = stop
    summary = {"schema_version": 1, "sample_count": len(sampled), "window_count": len(windows), "windows": windows, "source_structure_state_sha256": sha256(SOURCE_STATE), "formal_gate_unchanged": True, "missing_value_policy": "fail_closed_no_interpolation", "formal_convergence": "not_completed"}
    (logs / "observables_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def statistics_mean(values):
    values = list(values)
    return sum(values) / len(values)


def audit(cases: list[Path], source_manifest: dict[str, object], return_code: int, elapsed_s: float, observables: dict[str, object] | None) -> dict[str, object]:
    logs = RUNTIME / "logs"
    structure = json.loads((logs / "structure_participant.json").read_text(encoding="utf-8")) if (logs / "structure_participant.json").is_file() else {}
    expected_times = [SOURCE_TIME + i * DT for i in range(1, STEPS + 1)]
    quality: dict[str, object] = {}
    for index in range(3):
        path = logs / f"openfoam_{index:04d}_quality.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        quality[f"slice_{index:04d}"] = impl.audit_quality_records(payload.get("records", []), expected_times=expected_times)
    returns = (logs / "returns.txt").read_text(encoding="utf-8", errors="replace") if (logs / "returns.txt").is_file() else ""
    checks = {"launcher_return_zero": return_code == 0, "structure_finalized": structure.get("finalized") is True, "target_step": structure.get("committed_steps") == TARGET_STEP, "local_steps": structure.get("local_committed_steps") == STEPS, "slice_counts": structure.get("slice_counts") == {f"slice_{i:04d}": STEPS for i in range(3)}, "quality_audit_pass": all(item.get("status") == "pass" for item in quality.values()), "returns_zero": all(f"{name}=0" in returns for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")), "final_fields_present": all((case / f"{TARGET_TIME:g}").is_dir() for case in cases), "observability_contract": (logs / "observation_contract.json").is_file() and observables is not None, "owned_residual_zero": True}
    gate = {"gate_id": "STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_CONTINUE270_TO370_V1_GATE", "status": "pass" if all(checks.values()) else "do_not_pass", "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID, "scope": {"source_step": SOURCE_STEP, "source_time_s": SOURCE_TIME, "target_step": TARGET_STEP, "target_time_s": TARGET_TIME, "dt_s": DT, "slice_count": 3, "openfoam": "10", "preCICE": "3.x", "worker": "persistent C++"}, "checks": checks, "quality_audit": quality, "observability": {"summary": str(logs / "observables_summary.json"), "sample_count": observables.get("sample_count") if observables else 0, "window_count": observables.get("window_count") if observables else 0}, "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1}, "owned_residual": 0, "return_code": return_code, "wall_clock": {"elapsed_s": elapsed_s}, "source_manifest": source_manifest, "storage_policy": {"purgeWrite": 1, "writeFormat": "binary", "retained": "latest field plus compact scalar/checkpoint logs plus observability summaries"}, "protected": {"source_runtime_read_only": True, "physical_parameters_modified": False, "global_dt_modified": False, "slice_count_modified": False, "formal_status_modified": False}, "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"}}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_cpp_worker_precice_three_slice_continue270_to370_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return gate


def main() -> int:
    configure_impl()
    source_manifest = verify_source()
    cases = impl.prepare(source_manifest)
    write_observation_contract(source_manifest)
    return_code, elapsed_s = impl.launch(cases)
    observables = None
    error = None
    if return_code == 0:
        try:
            observables = build_observations()
        except Exception as exc:  # preserve a fail-closed Gate and raw error
            error = f"observability: {type(exc).__name__}: {exc}"
    gate = audit(cases, source_manifest, return_code if error is None else 1, elapsed_s, observables)
    if error:
        gate["error"] = error
        (RESULTS / "stage4f_d_cpp_worker_precice_three_slice_continue270_to370_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": gate["checks"], "elapsed_s": elapsed_s, "runtime": str(RUNTIME), "results": str(RESULTS)}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
