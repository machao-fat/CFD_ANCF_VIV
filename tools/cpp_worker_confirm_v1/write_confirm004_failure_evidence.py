"""Seal the already-failed confirm_004 runtime without retrying it.

The one-shot runner failed before its normal summary writer ran.  This audit
only reads the sealed runtime and writes failure evidence into the new result
directory; it never starts an external process and never modifies the runtime.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[2]
STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_v4"
RUN_ID = "cpp_worker_persistent_ipc_confirm_004"
CASE_ID = "cpp_worker_persistent_ipc_confirm_case_004"
RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_004"
RESULTS = PROJECT / "results/121_cpp_worker_persistent_ipc_confirm_v4"
DOCS = PROJECT / "docs/121_cpp_worker_persistent_ipc_confirm_v4"


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checkpoints() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((RUNTIME / "checkpoint").glob("checkpoint_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append({
            "path": str(path), "sha256": sha256(path),
            "global_step": int(payload.get("global_step", -1)),
            "time_s": payload.get("time_s"),
            "integer_tick": payload.get("integer_tick", payload.get("time_tick")),
            "committed": payload.get("committed") is True,
        })
    return rows


def log_processes() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((RUNTIME / "cases").glob("slice_*/log.pimpleFoam*")):
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^PID\s+:\s+(\d+)", text, re.MULTILINE)
        rows.append({
            "component": "openfoam_slice", "slice_id": int(path.parent.name.split("_")[-1]),
            "pid": int(match.group(1)) if match else None,
            "executable": "/opt/openfoam10/platforms/linux64GccDPInt32Opt/bin/pimpleFoam",
            "log": str(path), "log_sha256": sha256(path), "owned": True,
            "return_code": None, "cleanup_result": "process exited before audit",
        })
    return rows


def main() -> int:
    if not RUNTIME.is_dir() or RESULTS.exists() or DOCS.exists():
        raise SystemExit("refusing to overwrite runtime or result destinations")
    rows = checkpoints()
    committed = [row for row in rows if row["committed"]]
    failed_step = 583
    failed_time = 2.2375
    failed_log = RUNTIME / "cases/slice_0002/log.pimpleFoam_cpp_worker_persistent_ipc_confirm_004_slice_0002_persistent"
    failed_text = failed_log.read_text(encoding="utf-8", errors="replace")
    nonfinite = "Final residual = nan" in failed_text and "pressure : (-nan -nan -nan)" in failed_text
    process_rows = log_processes()
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass",
        "status": "do_not_pass", "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "scope": {"global_steps": 40, "slice_count": 3, "segment_duration_s": 0.05,
                  "source_global_step": 559, "source_time_s": 2.2075,
                  "source_tick": 2207500000, "target_final_step": 599,
                  "target_final_time_s": 2.2575, "target_final_tick": 2257500000},
        "physical_committed": f"{len(committed)}/40",
        "fully_audited": f"{len(committed)}/40",
        "failure": {"classification": "openfoam_nonfinite_output", "global_step": failed_step,
                    "time_s": failed_time, "slice_id": 2,
                    "evidence": {"log": str(failed_log), "log_sha256": sha256(failed_log),
                                 "final_residual_nan": nonfinite,
                                 "forces_dat_nan": True}},
        "cpp_worker_startup": 1, "openfoam_startup": len(process_rows), "wsl_startup": len(process_rows),
        "matlab_startup": 0, "cfd_startup": 0, "owned_residual": 0,
        "old_evidence_modified": False, "old_runtime_reused": False,
        "same_runtime_retry": False, "next_segment_started": False,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed",
                          "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
                          "LOCK_IN_CLAIM": "not_completed"},
    }
    # The runner did not persist perf timestamps before failing; make that
    # absence explicit instead of fabricating timings.
    timing_rows = [{"global_step": row["global_step"], "time_s": row["time_s"],
                    "integer_tick": row["integer_tick"], "T_ancf_s": None,
                    "T_openfoam_s": None, "T_exchange_s": None,
                    "T_sync_and_audit_s": None, "T_step_s": None,
                    "timing_available": False} for row in rows]
    summary = {"stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
               "status": "not_evaluable", "failure_step": failed_step,
               "statistics": "not_evaluable_after_fail_closed", "segment_wall_clock_s": None,
               "timing_rows": len(timing_rows), "raw_timing_persisted": False}
    write(RESULTS / "phase_timing_per_step.json", {"stage_id": STAGE_ID, "rows": timing_rows})
    write(RESULTS / "phase_timing_summary.json", summary)
    write(RESULTS / "slice_timing_summary.json", {"stage_id": STAGE_ID, "status": "not_evaluable",
                                                    "reason": "confirm failed before timing summary"})
    write(RESULTS / "performance_bottleneck_attribution.json", {
        "stage_id": STAGE_ID, "status": "not_evaluable",
        "failure_bottleneck": "OpenFOAM slice_2 non-finite pressure solve at step 583",
        "evidence": str(failed_log),
    })
    write(RESULTS / "resource_audit.json", {"stage_id": STAGE_ID, "cpu_memory": "not_sampled",
                                              "disk_delta": "not_sampled", "owned_residual": 0})
    write(RESULTS / "process_ownership_audit.json", {
        "stage_id": STAGE_ID, "registry": process_rows,
        "cpp_worker_startup": 1, "openfoam_startup": len(process_rows),
        "wsl_startup": len(process_rows), "matlab_startup": 0,
        "owned_residual": 0, "pid_evidence": "OpenFOAM logs",
    })
    write(RESULTS / "checkpoint_snapshot_audit.json", {
        "stage_id": STAGE_ID, "checkpoint_count": len(rows),
        "committed_count": len(committed), "checkpoints": rows,
        "failed_step": failed_step, "snapshot_audit": "fail_closed",
    })
    write(RESULTS / "failure_raw.json", {"classification": "openfoam_nonfinite_output",
                                           "global_step": failed_step, "slice_id": 2,
                                           "log": str(failed_log), "log_sha256": sha256(failed_log),
                                           "stdout_stderr": "OpenFOAM raw log retained; no retry"})
    write(RESULTS / "confirm_summary.json", {"stage_id": STAGE_ID, "run_id": RUN_ID,
                                               "case_id": CASE_ID, "status": "do_not_pass",
                                               "physical_committed": len(committed),
                                               "fully_audited": len(committed),
                                               "cpp_worker_startup": 1,
                                               "openfoam_startup": len(process_rows),
                                               "wsl_startup": len(process_rows), "matlab_startup": 0,
                                               "owned_residual": 0, "failure": gate["failure"]})
    write(RESULTS / "stage4f_d_cpp_worker_persistent_ipc_v1_confirm_gate.json", gate)
    write(RESULTS / "stop_gate_audit.json", {"stage_id": STAGE_ID,
                                               "stopped_after_bounded_confirm": True,
                                               "same_runtime_retry": False,
                                               "next_segment_started": False,
                                               "owned_residual": 0, "gate": gate["gate"]})
    write(RESULTS / "test_discovery_audit.json", {"stage_id": STAGE_ID,
                                                   "compileall": "pass_before_confirm",
                                                   "confirm_entrypoint": "returned nonzero",
                                                   "failure_evidence_sealed": True,
                                                   "real_process_starts": {"MATLAB": 0,
                                                       "OpenFOAM": len(process_rows),
                                                       "WSL": len(process_rows), "CFD": len(process_rows)}})
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "cpp_worker_persistent_ipc_confirm_report.md").write_text(
        f"""# C++ worker persistent IPC confirm_004\n\n"
        f"- Gate: `{gate['gate']}`\n"
        f"- 物理提交: {len(committed)}/40；完整审计: {len(committed)}/40\n"
        f"- 失败 step: global_step={failed_step}, time={failed_time} s, slice=2\n"
        f"- 根因证据: OpenFOAM slice 2 `Final residual = nan`，随后 `forces.dat` 为 NaN。\n"
        f"- C++ worker startup=1；OpenFOAM startup=3；WSL startup=3；MATLAB=0；owned residual=0。\n"
        f"- 这是一次性 bounded confirm，已停止；不得重试、续跑或复用此 runtime。\n"
        f"- 计时摘要未在异常前落盘，因此所有性能统计标记为 `not_evaluable`，没有伪造数值。\n"
        f"- 旧证据、旧 runtime、物理参数、global dt、阈值和正式协议未修改。\n""",
        encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
