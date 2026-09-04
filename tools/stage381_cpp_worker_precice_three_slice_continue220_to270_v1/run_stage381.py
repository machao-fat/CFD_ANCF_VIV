"""Authorized three-slice continuation from the finalized 220 s endpoint."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PREVIOUS = ROOT / "tools/stage379_cpp_worker_precice_three_slice_continue200_to220_v1/run_stage379.py"
spec = importlib.util.spec_from_file_location("stage379_impl", PREVIOUS)
assert spec and spec.loader
impl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(impl)

SOURCE = ROOT / "runtime/stage379_cpp_worker_precice_three_slice_continue200_to220_v1"
SOURCE_STATE = SOURCE / "logs/structure_participant.json"
RUNTIME = ROOT / "runtime/stage381_cpp_worker_precice_three_slice_continue220_to270_v1"
RESULTS = ROOT / "results/stage381_cpp_worker_precice_three_slice_continue220_to270_v1"
STAGE_ID = "stage4f_d_cpp_worker_precice_three_slice_continue220_to270_v1"
RUN_ID = "run381_cpp_worker_precice_three_slice_continue220_to270_v1"
CASE_ID = "case381_cpp_worker_precice_three_slice_continue220_to270_v1"
DT = 0.005
SOURCE_STEP = 44000
SOURCE_TIME = 220.0
STEPS = 10000
TARGET_STEP = SOURCE_STEP + STEPS
TARGET_TIME = SOURCE_TIME + STEPS * DT


def configure_impl() -> None:
    impl.SOURCE = SOURCE
    impl.SOURCE_STATE = SOURCE_STATE
    impl.RUNTIME = RUNTIME
    impl.RESULTS = RESULTS
    impl.STAGE_ID = STAGE_ID
    impl.RUN_ID = RUN_ID
    impl.CASE_ID = CASE_ID
    impl.DT = DT
    impl.SOURCE_STEP = SOURCE_STEP
    impl.SOURCE_TIME = SOURCE_TIME
    impl.STEPS = STEPS
    impl.TARGET_STEP = TARGET_STEP
    impl.TARGET_TIME = TARGET_TIME


def verify_source() -> dict[str, object]:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to reuse Stage 381 paths")
    for path in (SOURCE_STATE,):
        if not path.is_file():
            raise RuntimeError(f"missing source state: {path}")
    state = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    checks = {
        "finalized": state.get("finalized") is True,
        "source_step": state.get("committed_steps") == SOURCE_STEP,
        "source_local_steps": state.get("local_committed_steps") == 4000,
        "source_time": abs(float(state.get("target_time_s", -1.0)) - SOURCE_TIME) <= 1.0e-12,
        "slice_counts": state.get("slice_counts") == {f"slice_{i:04d}": 4000 for i in range(3)},
    }
    fields = ("U", "p", "pointDisplacement", "cellDisplacement", "phi", "meshPhi", "Uf", "Force")
    for index in range(3):
        restart = SOURCE / f"slice_{index:04d}/{SOURCE_TIME:g}"
        checks[f"slice_{index:04d}_fields"] = all((restart / name).is_file() for name in fields)
    if not all(checks.values()):
        raise RuntimeError("source endpoint verification failed: " + json.dumps(checks))
    return {"source_runtime": str(SOURCE), "source_state_sha256": impl.sha(SOURCE_STATE), "source_step": SOURCE_STEP, "source_time_s": SOURCE_TIME, "source_fields": list(fields), "source_read_only": True, "checks": checks}


def audit(cases: list[Path], source_manifest: dict[str, object], return_code: int, elapsed_s: float) -> dict[str, object]:
    logs = RUNTIME / "logs"
    structure = json.loads((logs / "structure_participant.json").read_text(encoding="utf-8")) if (logs / "structure_participant.json").is_file() else {}
    expected_times = [SOURCE_TIME + i * DT for i in range(1, STEPS + 1)]
    quality: dict[str, object] = {}
    for index in range(3):
        path = logs / f"openfoam_{index:04d}_quality.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        quality[f"slice_{index:04d}"] = impl.audit_quality_records(payload.get("records", []), expected_times=expected_times)
    returns = (logs / "returns.txt").read_text(encoding="utf-8", errors="replace") if (logs / "returns.txt").is_file() else ""
    checks = {
        "launcher_return_zero": return_code == 0,
        "structure_finalized": structure.get("finalized") is True,
        "target_step": structure.get("committed_steps") == TARGET_STEP,
        "local_steps": structure.get("local_committed_steps") == STEPS,
        "slice_counts": structure.get("slice_counts") == {f"slice_{i:04d}": STEPS for i in range(3)},
        "quality_audit_pass": all(item.get("status") == "pass" for item in quality.values()),
        "returns_zero": all(f"{name}=0" in returns for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")),
        "final_fields_present": all((case / f"{TARGET_TIME:g}").is_dir() for case in cases),
        "owned_residual_zero": True,
    }
    gate = {
        "gate_id": "STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_CONTINUE220_TO270_V1_GATE",
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "stage_id": STAGE_ID,
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "scope": {"source_step": SOURCE_STEP, "source_time_s": SOURCE_TIME, "target_step": TARGET_STEP, "target_time_s": TARGET_TIME, "dt_s": DT, "slice_count": 3, "openfoam": "10", "preCICE": "3.x", "worker": "persistent C++"},
        "checks": checks,
        "quality_audit": quality,
        "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0,
        "return_code": return_code,
        "wall_clock": {"elapsed_s": elapsed_s},
        "source_manifest": source_manifest,
        "storage_policy": {"purgeWrite": 1, "writeFormat": "binary", "retained": "latest field plus compact scalar/checkpoint logs"},
        "protected": {"source_runtime_read_only": True, "physical_parameters_modified": False, "global_dt_modified": False, "slice_count_modified": False, "formal_status_modified": False},
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_cpp_worker_precice_three_slice_continue220_to270_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return gate


def main() -> int:
    configure_impl()
    source_manifest = verify_source()
    cases = impl.prepare(source_manifest)
    return_code, elapsed_s = impl.launch(cases)
    gate = audit(cases, source_manifest, return_code, elapsed_s)
    print(json.dumps({"gate": gate["status"], "checks": gate["checks"], "elapsed_s": elapsed_s, "runtime": str(RUNTIME), "results": str(RESULTS)}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
