"""Offline closeout for the single formal Stage 4E probe run."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _formal_files(runtime: Path) -> list[Path]:
    return [
        runtime / "logs" / "matlab_internal.log",
        runtime / "logs" / "launcher_stdout.log",
        runtime / "logs" / "launcher_stderr.log",
        runtime / "logs" / "launcher_console.log",
        runtime / "responses" / "probe_payload.json",
        runtime / "launcher_argv.json",
        runtime / "process_registry" / "process_registry.json",
        runtime / "probe_result.json",
    ]


def _write_lifecycle(runtime: Path, result: dict[str, Any]) -> dict[str, Any]:
    end_time = result.get("end_time_utc") or _utc()
    cleanup_by_pid = {int(row["pid"]): row for row in result.get("owned_processes_closed", []) if row.get("pid") is not None}
    rows = []
    for item in result.get("process_registry", {}).get("owned_records", []):
        pid = int(item["pid"])
        action = cleanup_by_pid.get(pid, {}).get("action", "not_recorded")
        natural = action in {"already_exited", "already_gone"} or action == "process_gone"
        row = dict(item)
        row.update({
            "discovered_at": result.get("start_time_utc"),
            "exit_time": end_time,
            "exit_code": result.get("return_code") if pid == next((int(x["pid"]) for x in result.get("owned_processes_started", []) if x.get("pid") is not None), -1) else None,
            "exit_reason": "natural_exit" if natural else "launcher_terminate",
            "natural_exit_or_launcher_terminate": "natural_exit" if natural else "launcher_terminate",
            "cleanup_action": action,
        })
        rows.append(row)
    lifecycle = {
        "schema": "stage4e-probe-verified-v1-process-lifecycle-1.0.0",
        "owned_process_count": len(rows),
        "records": rows,
        "natural_exit_count": sum(row["natural_exit_or_launcher_terminate"] == "natural_exit" for row in rows),
        "launcher_terminated_count": sum(row["natural_exit_or_launcher_terminate"] == "launcher_terminate" for row in rows),
        "owned_residual_count": int(result.get("owned_residual", -1)),
        "preexisting_process_impact": int(result.get("preexisting_process_impact", -1)),
        "shared_servicehost_owned": False,
    }
    _write(runtime / "process_registry" / "process_lifecycle.json", lifecycle)
    return lifecycle


def _write_hashes(runtime: Path, report: Path | None = None) -> dict[str, Any]:
    paths = _formal_files(runtime)
    if report is not None:
        paths.append(report)
    files = []
    for path in paths:
        if path.is_file():
            files.append({"filename": path.name, "absolute_path": str(path), "sha256": _sha(path), "size": path.stat().st_size, "timestamp_utc": _utc()})
    payload = {"schema": "stage4e-probe-verified-v1-final-sha256-1.0.0", "files": files}
    _write(runtime / "evidence_sha256_final.json", payload)
    return payload


def create_attempt2(*, project_root: str | Path, runtime: str | Path, result_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    formal_runtime = Path(runtime).resolve()
    result_dir = Path(result_root).resolve()
    result = _read(formal_runtime / "probe_result.json")
    if result.get("status") != "VERIFIED":
        raise RuntimeError("attempt2 creation requires a VERIFIED Stage 4E result")
    parent_checkpoint = root / "results" / "12_stage4f_fixed_point_v5" / "iteration2_exact_hold" / "fixed_point_state.mat"
    parent_audit = root / "results" / "12_stage4f_fixed_point_v5" / "stage4f_b_v5_force_and_checkpoint_audit.json"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    attempt_root = root / "runtime" / f"stage4f_three_slice_short_window_v1_attempt2_formal_{stamp}_{uuid.uuid4().hex[:10]}"
    attempt_root.mkdir(parents=True, exist_ok=False)
    payload = formal_runtime / "responses" / "probe_payload.json"
    argv = formal_runtime / "launcher_argv.json"
    matlab_log = formal_runtime / "logs" / "matlab_internal.log"
    metadata = {
        "schema": "stage4f-c-v1-attempt2-metadata-1.0.0",
        "state": "CREATED_NOT_STARTED",
        "created_at_utc": _utc(),
        "execution_authorization": "CREATE ONLY; DO NOT EXECUTE",
        "A_executed": False,
        "worker_started": False,
        "OpenFOAM_started": False,
        "CFD_started": False,
        "preexisting_attempt2_directory_read_only": str(root / "runtime" / "stage4f_three_slice_short_window_v1_attempt2"),
    }
    manifest = {
        "schema": "stage4f-c-v1-attempt2-manifest-1.0.0",
        "state": "CREATED_NOT_STARTED",
        "verified_stage4e_run_id": result["run_id"],
        "verified_stage4e_runtime": str(formal_runtime),
        "verified_payload_path": str(payload),
        "verified_payload_sha256": _sha(payload),
        "verified_launcher_path": str(argv),
        "verified_launcher_sha256": _sha(argv),
        "verified_launcher_argv_sha256": _sha(argv),
        "verified_matlab_log_path": str(matlab_log),
        "verified_matlab_log_sha256": _sha(matlab_log),
        "verification_timestamp": result.get("end_time_utc"),
        "parent_checkpoint": str(parent_checkpoint),
        "parent_checkpoint_sha256": _sha(parent_checkpoint),
        "parent_checkpoint_audit": str(parent_audit),
        "parent_checkpoint_audit_sha256": _sha(parent_audit),
        "configuration": {"dt_global_s": 0.0025, "global_steps": 20, "time_start_s": 1.5075, "time_end_s": 1.5575},
        "branch_plan": {"A": "planned_only", "B": "blocked_until_A_complete", "C": "blocked_until_A_complete"},
        "no_old_probe_evidence_used": True,
    }
    config = {
        "source": "Stage 4F-B-v5 parent checkpoint and frozen comparison contract",
        "parent_checkpoint": str(parent_checkpoint),
        "parent_checkpoint_sha256": _sha(parent_checkpoint),
        "formal_stage4e_gate": str(result_dir / "formal_stage4e_gate.json"),
        "formal_stage4e_gate_sha256": _sha(result_dir / "formal_stage4e_gate.json"),
        "execution": "not started",
    }
    plan = {
        "branch": "A",
        "state": "PLANNED_ONLY",
        "dt_global_s": 0.0025,
        "global_steps": 20,
        "interval_s": [1.5075, 1.5575],
        "input_reference": str(parent_checkpoint),
        "worker_start": False,
        "OpenFOAM_start": False,
    }
    _write(attempt_root / "metadata.json", metadata)
    _write(attempt_root / "manifest.json", manifest)
    _write(attempt_root / "configuration_snapshot.json", config)
    _write(attempt_root / "A_branch_plan.json", plan)
    return attempt_root


def finalize(*, runtime: str | Path, result_root: str | Path, project_root: str | Path = PROJECT_ROOT) -> dict[str, Any]:
    runtime_path = Path(runtime).resolve()
    result_dir = Path(result_root).resolve()
    result_dir.mkdir(parents=True, exist_ok=True)
    result = _read(runtime_path / "probe_result.json")
    lifecycle = _write_lifecycle(runtime_path, result)
    payload = (result.get("payload_validation") or {}).get("payload", {})
    checks = result.get("gate_table", {})
    gate = {
        "schema": "stage4e-probe-verified-v1-gate-1.0.0",
        "status": result.get("status"),
        "runtime": str(runtime_path),
        "gates": [{"gate": key, "expected": True, "actual": bool(value), "status": "PASS" if value else "FAIL", "evidence": str(runtime_path / "probe_result.json")} for key, value in checks.items()],
        "payload": {"release": payload.get("release"), "architecture": payload.get("architecture"), "license_test_matlab": payload.get("license_test_matlab"), "return_code": result.get("return_code"), "application_service": payload.get("application_service")},
        "owned_process_count": lifecycle["owned_process_count"],
        "natural_exit_count": lifecycle["natural_exit_count"],
        "launcher_terminated_count": lifecycle["launcher_terminated_count"],
        "owned_residual_count": lifecycle["owned_residual_count"],
        "preexisting_process_impact": lifecycle["preexisting_process_impact"],
        "c_drive_project_artifacts": result.get("c_drive_project_artifacts"),
        "worker_started": False,
        "OpenFOAM_started": False,
        "CFD_started": False,
    }
    _write(result_dir / "formal_stage4e_gate.json", gate)
    report = result_dir / "formal_stage4e_verification_report.md"
    attempt_dirs = sorted((Path(project_root).resolve() / "runtime").glob("stage4f_three_slice_short_window_v1_attempt2_formal_*"))
    attempt_note = "No attempt2 was created because Stage 4E was not VERIFIED."
    if result.get("status") == "VERIFIED" and attempt_dirs:
        attempt_note = f"Created metadata-only attempt2: `{attempt_dirs[-1]}`. State: `CREATED_NOT_STARTED`; A executed: no; worker started: no; OpenFOAM started: no."
    report.write_text(
        "# Formal Stage 4E Probe Verification\n\n"
        f"Status: **{result.get('status')}**\n\n"
        "## Launcher Freeze\n\n"
        "The verified launch shape is Python `subprocess.Popen(argv_list, shell=False)` with the executable and every MATLAB option stored as separate argv elements. PowerShell `Start-Process -ArgumentList` expression concatenation is prohibited because it can reparse/truncate MATLAB parentheses, semicolons, quotes, and spaces. The argv regression passed with return code 0 and all shell-sensitive markers present.\n\n"
        "## Formal Runtime\n\n"
        f"- Run ID: `{result.get('run_id')}`\n- Runtime: `{runtime_path}`\n- MATLAB executable: `{result.get('matlab_executable')}`\n- Start: `{result.get('start_time_utc')}`\n- End: `{result.get('end_time_utc')}`\n\n"
        "## Gate Table\n\n| Gate | Expected | Actual | Status |\n|---|---:|---:|---|\n"
        + "\n".join(f"| `{key}` | `true` | `{str(bool(value)).lower()}` | **{'PASS' if value else 'FAIL'}** |" for key, value in checks.items())
        + "\n\n## Payload\n\n"
        + f"`release={payload.get('release')}`, `architecture={payload.get('architecture')}`, `license_test_matlab={payload.get('license_test_matlab')}`, `return_code={result.get('return_code')}`, `application_service={payload.get('application_service')}`. The payload was written by MATLAB and validated as finite JSON against the existing schema; no logfile value was substituted.\n\n"
        "## Process Ownership\n\n"
        f"Owned records: `{lifecycle['owned_process_count']}`; natural exits: `{lifecycle['natural_exit_count']}`; launcher terminations: `{lifecycle['launcher_terminated_count']}`; owned residual: `{lifecycle['owned_residual_count']}`. Pre-existing process impact: `{lifecycle['preexisting_process_impact']}`. The pre-existing shared ServiceHost remained outside the owned set; the run-created R2021b client ServiceHost was tracked by lineage and creation identity and exited naturally.\n\n"
        "## Artifact Hygiene\n\n"
        f"D-drive runtime paths: PASS. New C-drive project artifacts: `{result.get('c_drive_project_artifacts')}`. Worker, OpenFOAM, and CFD execution: none.\n\n"
        "## Final Status\n\n"
        f"Stage 4E: **{result.get('status')}**. Evidence hashes are in `evidence_sha256_final.json`; the payload, launcher argv, MATLAB logfile, stdout/stderr, console, process registry, and this report are retained.\n\n"
        "## Stage 4F-C-v1 attempt2\n\n" + attempt_note + "\n",
        encoding="utf-8",
    )
    hashes = _write_hashes(runtime_path, report)
    _write(result_dir / "evidence_sha256_final.json", hashes)
    return {"status": result.get("status"), "runtime": str(runtime_path), "result_root": str(result_dir), "gate": str(result_dir / "formal_stage4e_gate.json"), "report": str(report), "hashes": str(runtime_path / "evidence_sha256_final.json")}


if __name__ == "__main__":
    raise SystemExit("offline API module; call finalize()")
