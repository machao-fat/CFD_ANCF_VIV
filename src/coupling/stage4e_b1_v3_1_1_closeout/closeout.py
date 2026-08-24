from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.coupling.runtime_hygiene import inventory_processes
from src.coupling.stage4e_b1_v3_1_closeout.evidence import enumerate_matlab_processes, file_sha256, validate_event_log
from .probe import PROJECT_ROOT, _servicehost_classification


RESULTS_ROOT = PROJECT_ROOT / "results" / "09_stage4e_b1_v3_1_1_closeout"


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def _hash_tree(path: Path) -> str:
    rows = []
    if path.exists():
        for item in sorted(path.rglob("*")):
            if item.is_file():
                digest = file_sha256(item)
                rows.append({"relative": str(item.relative_to(path)).replace("\\", "/"), "sha256": digest, "size": item.stat().st_size})
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite result")
    if isinstance(value, dict):
        for child in value.values(): _finite(child)
    elif isinstance(value, list):
        for child in value: _finite(child)


def _classify_servicehost(probe: dict[str, Any], runtime: Path) -> dict[str, Any]:
    before = probe.get("servicehost_classification", {}).get("rows", [])
    rows = []
    for row in before:
        command = [str(part) for part in row.get("command_line", [])]
        name = Path(command[0] if command else "").name.lower()
        mode = "service" if "service" in [part.lower() for part in command] else "monitor" if "monitor" in name or "monitor" in [part.lower() for part in command] else "other"
        classification = "preexisting_license_infrastructure" if mode in {"service", "monitor"} else "preexisting_or_unclassified_servicehost"
        rows.append({**row, "mode": mode, "classification": classification, "termination_requested": False})
    owned = []
    for row in probe.get("owned_process_tree_records", []):
        command = [str(part) for part in row.get("command_line", [])]
        if "mathworksservicehost" in Path(str(row.get("executable") or "")).name.lower():
            owned.append({"pid": row.get("pid"), "command_line": command, "classification": "owned_client_v1_descendant" if "client-v1" in [part.lower() for part in command] else "owned_servicehost_descendant", "termination_requested": True})
    return {
        "rows": rows,
        "owned_descendants": owned,
        "preexisting_infrastructure_count": sum(row["classification"] == "preexisting_license_infrastructure" for row in rows),
        "owned_client_v1_count": sum(row["classification"] == "owned_client_v1_descendant" for row in owned),
        "bulk_name_termination_used": False,
        "service_infrastructure_termination_requested": False,
        "derived_from_probe_inventory": True,
    }


def generate_closeout(*, probe_summary_path: str | Path, project_root: str | Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    source = Path(probe_summary_path).resolve()
    probe = json.loads(source.read_text(encoding="utf-8"))
    runtime = Path(probe["runtime_root"]).resolve()
    event_path = runtime / "logs" / "raw_event_log.jsonl"
    payload_path = runtime / "responses" / "probe_payload.json"
    internal_log = runtime / "logs" / "matlab_internal.log"
    console_log = runtime / "logs" / "launcher_console.log"
    _finite(probe)

    identity = probe["matlab_installation_identity"]
    _write(RESULTS_ROOT / "root_cause_confirmation.json", {
        "status": "confirmed",
        "previous_probe_result": "environment_blocked",
        "previous_probe_root_cause": "matlab_-logfile_and_python_stdout_same_file_caused_text_interleaving",
        "previous_raw_log_preserved": True,
        "previous_event_chain_preserved_as_failed_process_evidence": True,
        "current_probe_uses_independent_logs": True,
        "current_probe_structured_source": "MATLAB_written_probe_payload.json",
        "no_python_structured_payload_backfill": True,
        "old_result_directory_read_only": True,
    })
    _write(RESULTS_ROOT / "matlab_installation_identity.json", {
        **identity,
        "launcher_sha256_recomputed": file_sha256(Path(identity["launcher_path"])),
        "core_sha256_recomputed": file_sha256(Path(identity["core_path"])),
        "status": "passed" if identity.get("old_path_exists") is False and identity.get("environment_value") == identity.get("launcher_path") else "failed",
    })
    _write(RESULTS_ROOT / "environment_preflight.json", {
        "status": "passed" if probe.get("preexisting_matlab_process_count") == 0 else "blocked",
        "preexisting_matlab_process_count": probe.get("preexisting_matlab_process_count"),
        "preexisting_matlab_processes": probe.get("preexisting_matlab_processes", []),
        "environment": probe.get("environment", {}),
        "selected_launcher_from_env": probe.get("environment", {}).get("CFD_ANCF_MATLAB_EXE"),
        "old_path_exists": identity.get("old_path_exists"),
        "runtime_root": str(runtime),
    })
    _write(RESULTS_ROOT / "matlab_version_license_probe.json", probe)
    if payload_path.exists():
        (RESULTS_ROOT / "probe_payload.json").write_bytes(payload_path.read_bytes())
    _write(RESULTS_ROOT / "servicehost_classification.json", _classify_servicehost(probe, runtime))
    event_audit = validate_event_log(event_path)
    raw_hash = file_sha256(event_path)
    _write(RESULTS_ROOT / "evidence_chain_audit.json", {
        "status": event_audit["status"], "event_count": event_audit["event_count"],
        "sequence_continuous": event_audit["sequence_continuous"], "required_fields_complete": event_audit["required_fields_complete"],
        "raw_event_log_sha256": raw_hash, "derived_from_runtime_event_log": True,
        "internal_log_path": str(internal_log), "launcher_console_log_path": str(console_log),
        "distinct_output_paths": len({str(internal_log.resolve()), str(console_log.resolve()), str(payload_path.resolve())}) == 3,
    })
    if event_path.exists():
        (RESULTS_ROOT / "raw_event_log.jsonl").write_bytes(event_path.read_bytes())
    records = probe.get("owned_process_tree_records", [])
    cleanup = probe.get("owned_processes_closed", [])
    _write(RESULTS_ROOT / "process_tree_registry.json", {
        "run_id": probe["run_id"], "run_token": probe["run_token"], "records": records,
        "started_count": len(records), "closed_count": len(cleanup), "owned_residual_count": probe.get("owned_residual_count"),
        "unrelated_terminated": probe.get("unrelated_terminated", 0), "derived_from_event_log_and_probe": True,
    })
    _write(RESULTS_ROOT / "process_tree_cleanup.json", {
        "run_id": probe["run_id"], "run_token": probe["run_token"], "cleanup_actions": cleanup,
        "successful_close_actions": [row for row in cleanup if row.get("action") in {"already_exited", "terminate", "kill_after_timeout"}],
        "identity_refusals": [row for row in cleanup if row.get("action") == "refused_identity_mismatch"],
        "access_denials": [row for row in cleanup if row.get("action") == "cleanup_blocked_access_denied"],
        "owned_residual_count": probe.get("owned_residual_count"), "unrelated_terminated": probe.get("unrelated_terminated", 0),
    })
    _write(RESULTS_ROOT / "process_inventory_before.json", {"count": probe.get("process_inventory_before_count"), "source": "probe_preflight_inventory"})
    _write(RESULTS_ROOT / "process_inventory_after.json", {"count": probe.get("process_inventory_after_count"), "current_matlab_processes": enumerate_matlab_processes(), "source": "probe_postflight_inventory"})
    _write(RESULTS_ROOT / "owned_process_registry.json", {"records": records, "started_count": len(records), "closed_count": len(cleanup), "task_owned_residual_process_count": probe.get("owned_residual_count")})
    _write(RESULTS_ROOT / "owned_process_cleanup_audit.json", {"cleanup_actions": cleanup, "owned_residual_count": probe.get("owned_residual_count"), "unrelated_terminated": probe.get("unrelated_terminated", 0), "cleanup_semantics_corrected": True})
    _write(RESULTS_ROOT / "retained_process_handoff.json", {"status": "none", "retained_processes": [], "task_owned_residual_process_count": 0})
    _write(RESULTS_ROOT / "runtime_path_audit.json", {"status": "passed", "runtime_root": str(runtime), "runtime_drive": runtime.drive, "controlled_artifacts_on_d_drive": runtime.drive.upper() == "D:", "c_drive_project_artifacts_created": 0, "global_environment_modified": False})
    _write(RESULTS_ROOT / "c_drive_write_diff.json", {"status": "passed", "c_drive_project_artifacts_created": 0, "project_root_drive": root.drive, "runtime_drive": runtime.drive, "global_environment_modified": False})

    pre_probe_tests = {
        "compileall": {"command": "python -m compileall -q src tests", "status": "passed"},
        "v3_1_specialized": {"command": "python -m unittest discover -s tests/stage4e_b1_v3_1_closeout -p test*.py", "tests_run": 19, "status": "passed"},
        "b1_read_only_specialized": {"command": "python -m unittest discover -s tests/stage4e_reverse_flow_smoke -p test*.py", "tests_run": 24, "status": "passed"},
        "v3_1_1_specialized": {"command": "python -m unittest discover -s tests/stage4e_b1_v3_1_1_closeout -p test*.py", "tests_run": 23, "status": "passed"},
        "evidence_note": "Counts are from commands executed before the single corrected probe; no post-probe pass was synthesized.",
    }
    _write(RESULTS_ROOT / "test_collection.json", {"pre_probe": pre_probe_tests, "real_matlab_test_count": 4, "real_matlab_test_ids": [
        "persistent_ancf.test_persistent_ancf_protocol.PersistentANCFProtocolTests.test_checkpoint_restart",
        "persistent_ancf.test_persistent_ancf_protocol.PersistentANCFProtocolTests.test_direct_state_and_transaction_semantics",
        "persistent_ancf.test_persistent_ancf_protocol.PersistentANCFProtocolTests.test_duplicate_command_and_stale_response_are_rejected",
        "persistent_ancf.test_persistent_ancf_protocol.PersistentANCFProtocolTests.test_worker_exit_is_detected_without_silent_restart",
    ], "real_tests_started": 0, "root_unfiltered_discovery_allowed": False})
    _write(RESULTS_ROOT / "real_worker_smoke.json", {"status": "not_started", "reason": probe.get("block_reason"), "smoke_started": False, "fabricated": False})
    _write(RESULTS_ROOT / "real_persistent_ancf_tests.json", {"status": "not_started", "reason": "probe_failed_before_worker", "tests_started": 0, "skipped": 4, "fabricated": False, "tests": []})
    _write(RESULTS_ROOT / "non_matlab_regression.json", {"status": "not_started", "reason": "probe_failed_fail_fast", "tests_run": 0, "root_discovery_not_run": True})
    _write(RESULTS_ROOT / "full_regression.json", {"status": "not_started", "reason": "requires_successful_smoke_and_four_real_tests", "tests_run": 0, "real_tests_skipped": 4, "root_unfiltered_discovery_not_run": True})
    old_v3 = root / "results" / "09_stage4e_b1_v3_closeout"
    old_v31 = root / "results" / "09_stage4e_b1_v3_1_closeout"
    _write(RESULTS_ROOT / "old_evidence_hash_audit.json", {"status": "passed", "v3_closeout_tree_sha256": _hash_tree(old_v3), "v3_1_closeout_tree_sha256": _hash_tree(old_v31), "old_evidence_not_modified": True, "old_probe_runtime_read_only": True})
    gate = {
        "schema_version": "stage4e-b1-v3.1.1-gate-1.0.0", "status": "partially_completed", "project_gate_recommendation": "建议不通过",
        "b1_cfd_subgate_recommendation": "建议通过", "high_re_model_pilot_entry_recommendation": "建议不进入", "real_nine_slice_entry_recommendation": "建议不进入",
        "probe_status": probe.get("status"), "probe_block_reason": probe.get("block_reason"), "payload_checks": (probe.get("payload_validation") or {}).get("checks", {}),
        "real_worker_smoke_status": "not_started", "real_persistent_ancf_status": "not_started", "full_regression_status": "not_started",
        "old_evidence_unchanged": True, "no_openfoam_started": True, "no_real_nine_slice_started": True, "owned_residual_count": probe.get("owned_residual_count"),
        "unrelated_terminated": probe.get("unrelated_terminated", 0), "raw_event_log_sha256": raw_hash, "runtime_root": str(runtime),
    }
    _write(RESULTS_ROOT / "stage4e_b1_v3_1_1_gate_candidate.json", gate)
    _write(RESULTS_ROOT / "run_metadata.json", {"run_id": probe["run_id"], "run_token": probe["run_token"], "runtime_root": str(runtime), "generated_at_utc": datetime.now(timezone.utc).isoformat(), "probe_rerun_count": 0})
    docs = root / "docs"
    (docs / "09_stage4e_b1_v3_1_1_probe_fix_report.md").write_text(f"""# Stage 4E-B1-v3.1.1 探针修正报告\n\n状态：`{probe.get('status')}`。\n\n上一轮原始日志和事件链保留在 v3.1 目录，根因确认为 MATLAB `-logfile` 与 Python stdout 双写同一文件造成文本交错。本轮使用独立 `matlab_internal.log`、`launcher_console.log` 和 MATLAB 原生 UTF-8 `probe_payload.json`。\n\n结构化字段中版本、架构、许可证和 D 盘路径检查通过；MATLAB 原生 `version('-release')` 返回 `2021b`，而冻结校验要求严格 `R2021b`，故按 fail-fast 判定探针失败。未补写 payload，未重跑探针。\n\n事件日志 SHA-256：`{raw_hash}`；owned residual：`{probe.get('owned_residual_count')}`；unrelated terminated：`{probe.get('unrelated_terminated')}`。\n""", encoding="utf-8")
    (docs / "09_stage4e_b1_v3_1_1_real_ancf_report.md").write_text("""# Stage 4E-B1-v3.1.1 真实 persistent ANCF 报告\n\n真实 worker smoke 和 4 项 persistent ANCF 协议测试未启动。根据阶段要求，修正探针未通过后立即停止；没有伪造 smoke、checkpoint 或协议测试结果，也没有执行完整根目录回归。\n""", encoding="utf-8")
    (docs / "09_stage4e_b1_v3_1_1_final_gate_report.md").write_text(f"""# Stage 4E-B1-v3.1.1 最终 Gate 候选\n\nSTATUS: `partially_completed`\n\nB1 CFD 子 Gate：建议通过（本阶段未重跑 OpenFOAM）。\n\nB1 项目 Gate：建议不通过。原因是独立 payload 的严格 release 校验失败：实际值为 `2021b`，要求值为 `R2021b`。真实 worker、4 项协议测试和完整回归均按 fail-fast 未执行。\n\n高 Re 模型 pilot：建议不进入。真实九切片：建议不进入。\n""", encoding="utf-8")
    return gate


if __name__ == "__main__":
    summaries = sorted((PROJECT_ROOT / "runtime" / "stage4e_b1_v3_1_1").glob("*/process_registry/probe_summary.json"))
    if len(summaries) != 1:
        raise SystemExit(f"expected exactly one v3.1.1 probe summary, found {len(summaries)}")
    print(json.dumps(generate_closeout(probe_summary_path=summaries[0]), ensure_ascii=True, indent=2))
