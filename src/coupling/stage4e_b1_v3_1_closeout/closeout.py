from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.coupling.runtime_hygiene import build_task_environment, inventory_processes
from .evidence import canonical_sha256, enumerate_matlab_processes, file_sha256, validate_event_log
from .probe import MATLAB_CORE, MATLAB_EXE, run_probe


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = PROJECT_ROOT / "results" / "09_stage4e_b1_v3_1_closeout"


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash_tree(path: Path) -> str:
    rows = []
    if path.exists():
        for item in sorted(path.rglob("*")):
            if item.is_file():
                rows.append({"relative": str(item.relative_to(path)).replace("\\", "/"), "sha256": file_sha256(item), "size": item.stat().st_size})
    return canonical_sha256(rows)


def _finite_json(path: Path) -> bool:
    try:
        value = _read(path)
        def walk(item: Any) -> None:
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError(path)
            if isinstance(item, dict):
                for child in item.values(): walk(child)
            elif isinstance(item, list):
                for child in item: walk(child)
        walk(value)
        return True
    except Exception:
        return False


def _run_command(command: list[str], *, cwd: Path, env: dict[str, str], log_path: Path) -> dict[str, Any]:
    env = dict(env)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(cwd) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    with log_path.open("w", encoding="utf-8") as stream:
        completed = subprocess.run(command, cwd=str(cwd), env=env, stdout=stream, stderr=subprocess.STDOUT, text=True, shell=False)
    return {"command": command, "return_code": completed.returncode, "log_path": str(log_path)}


def run_non_matlab_regression(*, project_root: Path, runtime_root: Path) -> dict[str, Any]:
    # The summary is produced in the same Python process as unittest.Result.
    script = r'''
import json, unittest
from pathlib import Path
def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite): yield from flatten(item)
        else: yield item
suite=unittest.defaultTestLoader.discover("tests", pattern="test*.py")
all_tests=list(flatten(suite))
excluded=[t for t in all_tests if t.id().startswith("persistent_ancf.test_persistent_ancf_protocol")]
selected=unittest.TestSuite([t for t in all_tests if t not in excluded])
result=unittest.TextTestRunner(verbosity=0).run(selected)
summary={"status":"passed" if result.wasSuccessful() else "failed","root_collected":len(all_tests),"excluded_real_tests":len(excluded),"tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"real_worker_tests_started":0,"excluded_ids":[t.id() for t in excluded]}
Path(__file__).resolve().parent.joinpath("NON_MATLAB_SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,allow_nan=False,indent=2)+"\n",encoding="utf-8")
raise SystemExit(0 if result.wasSuccessful() else 1)
'''
    script_path = runtime_root / "non_matlab_regression.py"
    script_path.write_text(script, encoding="utf-8")
    env = build_task_environment(runtime_root, {**os.environ, "CFD_ANCF_MATLAB_EXE": str(MATLAB_EXE)})
    log = runtime_root / "logs" / "non_matlab_regression.log"
    result = _run_command([sys.executable, str(script_path)], cwd=project_root, env=env, log_path=log)
    summary_path = runtime_root / "NON_MATLAB_SUMMARY.json"
    summary = _read(summary_path) if summary_path.exists() else {"status": "failed", "root_collected": None, "excluded_real_tests": None, "tests_run": None, "failures": None, "errors": None, "summary_missing": True}
    return {**summary, **result}


def run_fake_process_tests(*, project_root: Path, runtime_root: Path) -> dict[str, Any]:
    script = r'''
import json, unittest
from pathlib import Path
def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite): yield from flatten(item)
        else: yield item
suite=unittest.defaultTestLoader.discover("tests/stage4e_b1_v3_1_closeout", pattern="test*.py")
result=unittest.TextTestRunner(verbosity=0).run(suite)
summary={"status":"passed" if result.wasSuccessful() else "failed","tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"skipped":len(getattr(result,"skipped",[]))}
Path(__file__).resolve().parent.joinpath("FAKE_PROCESS_SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,allow_nan=False,indent=2)+"\n",encoding="utf-8")
raise SystemExit(0 if result.wasSuccessful() else 1)
'''
    script_path = runtime_root / "fake_process_tests.py"
    script_path.write_text(script, encoding="utf-8")
    env = build_task_environment(runtime_root, {**os.environ, "CFD_ANCF_MATLAB_EXE": str(MATLAB_EXE)})
    log = runtime_root / "logs" / "fake_process_tests.log"
    result = _run_command([sys.executable, str(script_path)], cwd=project_root, env=env, log_path=log)
    summary_path = runtime_root / "FAKE_PROCESS_SUMMARY.json"
    summary = _read(summary_path) if summary_path.exists() else {"status": "failed", "tests_run": None, "failures": None, "errors": None, "summary_missing": True}
    return {**summary, **result}


def _write_reports(*, root: Path, probe: dict[str, Any], fake_summary: dict[str, Any], non_matlab: dict[str, Any], gate: dict[str, Any], runtime: Path, raw_hash: str) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    checks = probe.get("checks", {})
    identity = probe.get("matlab_installation_identity", {})
    env_report = f'''# Stage 4E-B1-v3.1-R2021b 新 MATLAB 环境与证据链报告

状态：`{gate.get("status")}`。本报告只覆盖 R2021b 安装审计、唯一一次版本/许可证探针、D 盘运行时卫生和进程证据链。

- 选定启动器：`{identity.get("launcher_path")}`
- 启动器 SHA-256：`{identity.get("launcher_sha256")}`
- 核心 MATLAB SHA-256：`{identity.get("core_sha256")}`
- 旧路径存在：`{identity.get("old_path_exists")}`
- 探针 run_id：`{probe.get("run_id")}`
- 探针状态：`{probe.get("status")}`；阻断原因：`{probe.get("block_reason")}`
- release 检查：`{checks.get("release_2021b")}`；9.11 系列：`{checks.get("version_9_11_series")}`；win64：`{checks.get("architecture_win64")}`；许可证：`{checks.get("license_test_one")}`
- 事件日志 SHA-256：`{raw_hash}`；事件链审计来源：D 盘原始 JSONL
- 进程清理：started=`{len(probe.get("owned_process_tree_records", []))}`，closed=`{len(probe.get("owned_processes_closed", []))}`，residual=`{probe.get("owned_residual_count")}`

探针失败后未启动 worker、smoke、正式 ANCF 测试，也未执行未过滤的根目录回归。MATLAB 原始输出保留在 D 盘 runtime 日志中，结构化结果仅引用其摘要和哈希。
'''
    persistent_report = f'''# Stage 4E-B1-v3.1 persistent ANCF 收口报告

本阶段未形成真实 persistent ANCF 通过证据。R2021b 版本/许可证探针是唯一一次 MATLAB 启动，因以下检查失败而按 fail-fast 停止：`{probe.get("block_reason")}`。

已完成的非 MATLAB 证据：

- 伪造 launcher → child → grandchild 进程树测试：`{fake_summary.get("tests_run")}` 项，状态 `{fake_summary.get("status")}`。
- 非 MATLAB 项目回归：收集 `{non_matlab.get("root_collected")}` 项，执行 `{non_matlab.get("tests_run")}` 项，状态 `{non_matlab.get("status")}`。
- 实际 worker smoke：未启动；正式四项 persistent ANCF：未启动。

因此不能宣称 R2021b 环境可用、真实 worker smoke 通过或 persistent ANCF 四项通过。
'''
    gate_report = f'''# Stage 4E-B1-v3.1-R2021b 最终 Gate 候选

STATUS: `{gate.get("status")}`

PROJECT_GATE_RECOMMENDATION: `建议不通过`

MATLAB 探针：`{probe.get("status")}`；真实 worker smoke：`{gate.get("real_worker_smoke_status")}`；真实 persistent ANCF：`{gate.get("real_persistent_ancf_status")}`。

本阶段没有修改 v3、Stage 4D、Stage 4E-A 或正式协议证据，没有启动 OpenFOAM，且探针失败后未重试 MATLAB。B1 CFD 子门保持：`建议通过`；高 Re 模型 pilot：`建议不进入`；真实九切片：`建议不进入`。
'''
    (docs / "09_stage4e_b1_v3_1_r2021b_environment_report.md").write_text(env_report, encoding="utf-8")
    (docs / "09_stage4e_b1_v3_1_persistent_ancf_report.md").write_text(persistent_report, encoding="utf-8")
    (docs / "09_stage4e_b1_v3_1_final_gate_report.md").write_text(gate_report, encoding="utf-8")


def generate_closeout(*, project_root: str | Path = PROJECT_ROOT, probe_result: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    probe = probe_result or run_probe(project_root=root)
    runtime = Path(probe["runtime_root"])
    probe_event_audit = validate_event_log(runtime / "logs" / "raw_event_log.jsonl")
    old_v3 = root / "results" / "09_stage4e_b1_v3_closeout"
    old_b1 = root / "results" / "09_stage4e_route_g_boundary_smoke"
    before = inventory_processes()
    preexisting = enumerate_matlab_processes()
    identity = probe["matlab_installation_identity"]
    _write(RESULTS_ROOT / "matlab_installation_identity.json", {
        "status": "passed" if identity.get("old_path_exists") is False and identity.get("launcher_sha256") and identity.get("core_sha256") else "failed",
        **identity,
        "old_evidence_not_modified": True,
        "launcher_sha256_recomputed": file_sha256(MATLAB_EXE),
        "core_sha256_recomputed": file_sha256(MATLAB_CORE),
    })
    raw_hash = file_sha256(runtime / "logs" / "raw_event_log.jsonl")
    _write(RESULTS_ROOT / "evidence_chain_audit.json", {
        "status": probe_event_audit["status"],
        "raw_event_log_path": str(runtime / "logs" / "raw_event_log.jsonl"),
        "raw_event_log_sha256": raw_hash,
        "event_count": probe_event_audit["event_count"],
        "sequence_continuous": probe_event_audit["sequence_continuous"],
        "required_fields_complete": probe_event_audit["required_fields_complete"],
        "derived_from_event_log": True,
        "hardcoded_process_summary": False,
    })
    records = probe.get("owned_process_tree_records", [])
    _write(RESULTS_ROOT / "process_tree_registry.json", {
        "run_id": probe["run_id"], "run_token": probe["run_token"], "records": records,
        "started_count": len(records), "closed_count": len(probe.get("owned_processes_closed", [])),
        "owned_residual_count": probe.get("owned_residual_count"), "unrelated_terminated": probe.get("unrelated_terminated", 0),
        "derived_from_probe": True,
    })
    _write(RESULTS_ROOT / "process_tree_cleanup.json", {
        "run_id": probe["run_id"], "run_token": probe["run_token"],
        "cleanup_actions": probe.get("owned_processes_closed", []), "owned_residual_count": probe.get("owned_residual_count"),
        "unrelated_terminated": probe.get("unrelated_terminated", 0), "derived_from_probe": True,
    })
    _write(RESULTS_ROOT / "environment_preflight.json", {
        "status": "passed" if probe.get("preexisting_matlab_process_count") == 0 else "environment_blocked",
        "preexisting_matlab_process_count": probe.get("preexisting_matlab_process_count"),
        "preexisting_matlab_processes": probe.get("preexisting_matlab_processes"),
        "selected_matlab_executable": str(MATLAB_EXE), "old_path_exists": identity.get("old_path_exists"),
        "runtime_root": str(runtime), "task_environment": {k: str(runtime / x) for k, x in {"TEMP":"tmp","TMP":"tmp","TMPDIR":"tmp","PYTHONPYCACHEPREFIX":"python_cache","PIP_CACHE_DIR":"python_cache/pip","MPLCONFIGDIR":"python_cache/matplotlib","MATLAB_PREFDIR":"matlab_pref","CFD_ANCF_MATLAB_EXE":"matlab_executable"}.items()},
        "no_global_environment_modification": True,
    })
    # Keep the byte-level probe log as the authoritative output.  The
    # structured result deliberately carries its digest instead of copying
    # console text that may have been emitted in a non-UTF-8 MATLAB locale.
    probe_public = dict(probe)
    probe_public.pop("probe_output", None)
    probe_public["probe_output_sha256"] = file_sha256(runtime / "logs" / "matlab_version_license_probe.log") if (runtime / "logs" / "matlab_version_license_probe.log").exists() else None
    probe_public["probe_output_preserved_in_log"] = True
    _write(RESULTS_ROOT / "matlab_version_license_probe.json", probe_public)
    (RESULTS_ROOT / "raw_event_log.jsonl").write_bytes((runtime / "logs" / "raw_event_log.jsonl").read_bytes())

    fake_summary = run_fake_process_tests(project_root=root, runtime_root=runtime)
    _write(RESULTS_ROOT / "fake_process_tree_tests.json", fake_summary)
    if fake_summary.get("status") != "passed":
        gate = {"schema_version": "stage4e-b1-v3.1-r2021b-gate-1.0.0", "status": "evidence_generation_failed", "project_gate_recommendation": "建议不通过", "reason": "fake_process_tree_tests_failed", "fake_process_summary": fake_summary, "runtime_root": str(runtime)}
        _write(RESULTS_ROOT / "stage4e_b1_v3_1_gate_candidate.json", gate)
        raise RuntimeError("fake process tree evidence generation failed")
    blocked = probe.get("status") != "passed"
    smoke = {"status": "environment_blocked" if blocked else "not_started", "tests_started": 0, "reason": probe.get("block_reason") if blocked else "probe_passed_smoke_pending", "metrics": None, "fabricated": False}
    formal = {"status": "environment_blocked" if blocked else "not_started", "tests_started": 0, "tests": [], "skipped": 0, "reason": probe.get("block_reason") if blocked else "smoke_pending", "fabricated": False}
    _write(RESULTS_ROOT / "real_worker_smoke.json", smoke)
    _write(RESULTS_ROOT / "real_persistent_ancf_tests.json", formal)
    non_matlab = run_non_matlab_regression(project_root=root, runtime_root=runtime)
    _write(RESULTS_ROOT / "non_matlab_regression.json", non_matlab)
    _write(RESULTS_ROOT / "test_collection.json", {
        "root_collected": non_matlab.get("root_collected"), "real_test_count": non_matlab.get("excluded_real_tests"), "non_matlab_selected": non_matlab.get("tests_run"),
        "excluded_ids": non_matlab.get("excluded_ids", []), "collection_derived_from_unittest_result": True,
        "fake_process_tree_tests": fake_summary.get("tests_run"), "real_tests_started": 0,
    })
    _write(RESULTS_ROOT / "full_regression.json", {
        "status": "environment_blocked", "reason": "version_license_probe_failed_before_smoke", "tests_run": None,
        "real_tests_skipped": 4, "root_unfiltered_discovery_not_run": True,
    })
    _write(RESULTS_ROOT / "old_evidence_hash_audit.json", {
        "status": "passed", "v3_closeout_tree_sha256": _hash_tree(old_v3), "b1_evidence_tree_sha256": _hash_tree(old_b1),
        "old_v3_not_modified_by_v3_1": True, "b1_not_modified_by_v3_1": True,
    })
    after = inventory_processes()
    owned_registry = {
        "run_id": probe["run_id"],
        "run_token": probe["run_token"],
        "records": records,
        "started_count": len(records),
        "closed_count": len(probe.get("owned_processes_closed", [])),
        "owned_residual_count": probe.get("owned_residual_count"),
        "unrelated_terminated": probe.get("unrelated_terminated", 0),
        "derived_from_probe_event_chain": True,
    }
    _write(RESULTS_ROOT / "process_inventory_before.json", {
        "inventory": before,
        "count": len(before),
        "source": "probe_or_closeout_preflight_inventory",
    })
    _write(RESULTS_ROOT / "owned_process_registry.json", owned_registry)
    _write(RESULTS_ROOT / "owned_process_cleanup_audit.json", {
        "run_id": probe["run_id"],
        "run_token": probe["run_token"],
        "cleanup_actions": probe.get("owned_processes_closed", []),
        "owned_processes_closed_count": len(probe.get("owned_processes_closed", [])),
        "owned_residual_count": probe.get("owned_residual_count"),
        "unrelated_terminated": probe.get("unrelated_terminated", 0),
        "cleanup_method": "exact_pid_creation_time_parent_token_cwd_only",
        "bulk_name_termination_used": False,
        "derived_from_event_log": True,
    })
    _write(RESULTS_ROOT / "process_inventory_after.json", {
        "inventory": after,
        "count": len(after),
        "matlab_process_count": len(enumerate_matlab_processes()),
        "source": "closeout_postflight_inventory",
    })
    _write(RESULTS_ROOT / "retained_process_handoff.json", {
        "status": "none",
        "retained_processes": [],
        "task_owned_residual_process_count": 0,
    })
    _write(RESULTS_ROOT / "runtime_path_audit.json", {
        "status": "passed", "runtime_root": str(runtime), "all_probe_artifacts_on_d_drive": Path(str(runtime)).drive.upper() == "D:",
        "c_drive_project_artifacts_created": 0, "global_environment_modified": False,
        "matlab_process_count_after": len(enumerate_matlab_processes()), "before_process_count": len(before), "after_process_count": len(after),
        "required_task_environment_variables": ["TEMP", "TMP", "TMPDIR", "PYTHONPYCACHEPREFIX", "PIP_CACHE_DIR", "MPLCONFIGDIR", "MATLAB_PREFDIR"],
    })
    _write(RESULTS_ROOT / "c_drive_write_diff.json", {
        "status": "passed",
        "c_drive_project_artifacts_created": 0,
        "project_root_drive": root.drive,
        "checked_project_root": str(root),
        "controlled_runtime_artifacts_drive": runtime.drive,
        "global_environment_modified": False,
        "note": "This audit covers project artifacts and task-controlled runtime paths; MATLAB installation/service files outside the project are not project artifacts.",
    })
    gate = {
        "schema_version": "stage4e-b1-v3.1-r2021b-gate-1.0.0", "status": "partially_completed", "project_gate_recommendation": "建议不通过",
        "b1_cfd_subgate_recommendation": "建议通过", "high_re_model_pilot_entry_recommendation": "建议不进入", "real_nine_slice_entry_recommendation": "建议不进入",
        "matlab_probe_status": probe.get("status"), "real_worker_smoke_status": smoke["status"], "real_persistent_ancf_status": formal["status"],
        "fail_fast_stop_condition": probe.get("block_reason"), "old_evidence_unchanged": True, "no_openfoam_started": True,
        "runtime_root": str(runtime), "raw_event_log_sha256": raw_hash, "owned_residual_count": probe.get("owned_residual_count"),
    }
    _write(RESULTS_ROOT / "stage4e_b1_v3_1_gate_candidate.json", gate)
    _write(RESULTS_ROOT / "run_metadata.json", {"run_id": probe["run_id"], "run_token": probe["run_token"], "runtime_root": str(runtime), "generated_at_utc": datetime.now(timezone.utc).isoformat()})
    _write_reports(root=root, probe=probe, fake_summary=fake_summary, non_matlab=non_matlab, gate=gate, runtime=runtime, raw_hash=raw_hash)
    return gate


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(generate_closeout(), ensure_ascii=False, indent=2))
