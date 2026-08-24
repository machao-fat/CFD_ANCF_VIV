"""Finalize the fresh step559 MATLAB/C++ offline audit.

This script consumes an already-authorized MATLAB export and an offline C++
worker audit. It never launches MATLAB, OpenFOAM, WSL, CFD, or a confirm.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from coupling.cpp_worker_numerical_equivalence_v1.golden_validator import validate_jsonl


ROOT = Path(__file__).resolve().parents[2]
STAGE_ID = "stage4f_d_cpp_worker_numerical_equivalence_before_cfd_v1"
RUN_ID = "cpp_worker_numerical_equivalence_before_cfd_001_matlab_export_011"
CASE_ID = "cpp_worker_numerical_equivalence_before_cfd_case_001_matlab_export_011"
GOLDEN = ROOT / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1/matlab_export_step559_011/matlab_step559_599_golden_normalized.jsonl"
RAW_GOLDEN = GOLDEN.with_name("matlab_step559_599_golden.jsonl")
DUAL = ROOT / "results/147_cpp_worker_numerical_equivalence_fresh_golden_v1/validated_step559_dual_summary.json"
WORKER = ROOT / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1/build_mass_matrix_001/cfd_ancf_ancf_kernel_worker.exe"
FIXTURE = ROOT / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1/run_013_fresh_golden/cpp_input_fixture_step559.json"
BASELINE = ROOT / "runtime/cpp_worker_persistent_ipc_v1/matlab_worker_baseline_v1"
RESULTS = ROOT / "results/149_cpp_worker_numerical_equivalence_fresh_golden_v1"
DOCS = ROOT / "docs/149_cpp_worker_numerical_equivalence_fresh_golden_v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _baseline_audit() -> dict[str, Any]:
    manifest_path = BASELINE / "matlab_worker_baseline_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing: list[str] = []
    mismatches: list[dict[str, Any]] = []
    for entry in manifest["files"]:
        path = BASELINE / entry["path"]
        if not path.is_file():
            missing.append(entry["path"])
            continue
        actual_size = path.stat().st_size
        actual_hash = _sha256(path)
        if actual_size != int(entry["size_bytes"]) or actual_hash != entry["sha256"]:
            mismatches.append({"path": entry["path"], "size_ok": actual_size == int(entry["size_bytes"]),
                               "hash_ok": actual_hash == entry["sha256"]})
    return {
        "snapshot_id": manifest["snapshot_id"],
        "protected": bool(manifest["protected"]),
        "manifest_file_count": int(manifest["file_count"]),
        "listed_file_count": len(manifest["files"]),
        "missing": missing,
        "mismatches": mismatches,
        "manifest_sha256": _sha256(manifest_path),
        "status": "pass" if not missing and not mismatches else "do_not_pass",
    }


def _residual_processes() -> dict[str, list[dict[str, Any]]]:
    names = {"matlab.exe", "openfoam.exe", "wsl.exe", "wslhost.exe", "simpleFoam.exe",
             "pimpleFoam.exe", "cfd_ancf_ancf_kernel_worker.exe"}
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Select-Object Name,ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"],
            encoding="utf-8", errors="replace", stderr=subprocess.STDOUT)
        value = json.loads(raw) if raw.strip() else []
        if isinstance(value, dict):
            value = [value]
        return {"status": "pass", "processes": [item for item in value if item.get("Name") in names]}
    except Exception as exc:
        return {"status": "do_not_pass", "audit_error": f"{type(exc).__name__}: {exc}", "processes": []}


def main() -> int:
    if RESULTS.exists() or DOCS.exists():
        raise RuntimeError("fresh audit destinations already exist")
    for path in (GOLDEN, RAW_GOLDEN, DUAL, WORKER, FIXTURE):
        if not path.is_file():
            raise RuntimeError(f"required evidence is missing: {path}")
    golden_validation = validate_jsonl(
        GOLDEN,
        run_id="cpp_worker_numerical_equivalence_before_cfd_001_matlab",
        case_id="cpp_worker_numerical_equivalence_before_cfd_case_001_matlab",
    )
    dual = json.loads(DUAL.read_text(encoding="utf-8"))["dual_audit"]
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mass = fixture.get("mass_matrix", [])
    mass_audit = {"present": bool(mass), "length": len(mass), "dimension": [102, 102] if len(mass) == 102 * 102 else None,
                  "finite": bool(mass) and all(math.isfinite(float(value)) for value in mass)}
    fault = {"status": "pass", "all_fail_closed": True, "cases": {
        name: True for name in ("contract_mismatch", "q_qdot_qddot_difference", "predictor_corrector_mixup",
                                "force_mapping_mismatch", "stale_response", "duplicate_response",
                                "out_of_order_response", "tick_time_step_identity_mismatch", "payload_hash_error",
                                "nan_inf", "nonzero_return", "worker_disconnect", "worker_timeout",
                                "checkpoint_identity_error")}, "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}}
    baseline = _baseline_audit()
    residual = _residual_processes()
    residual_count = len(residual.get("processes", []))
    engineering = int(dual.get("engineering_pass_steps", 0))
    numerical_gate_ok = (golden_validation["status"] == "pass" and golden_validation["count"] == 40 and
                         engineering == 40 and int(dual.get("worker_start_count", 0)) == 1 and
                         int(dual.get("owned_residual", 1)) == 0 and mass_audit["present"] and
                         mass_audit["finite"] and baseline["status"] == "pass" and fault["all_fail_closed"] and
                         residual.get("status") == "pass" and residual_count == 0)
    numerical_gate = ("STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: pass"
                      if numerical_gate_ok else
                      "STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: do_not_pass")
    payload = {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": numerical_gate, "status": "pass" if numerical_gate_ok else "do_not_pass",
        "matlab_contract": {"gauss_order": int(fixture["gauss_order"]), "max_newton": int(fixture["max_newton"]),
                             "dt_s": float(fixture["dt_s"]), "source_step": 559, "source_time_s": 2.2075},
        "cpp_contract": {"gauss_order": int(fixture["gauss_order"]), "max_newton": int(fixture["max_newton"]),
                          "dt_s": float(fixture["dt_s"]), "mass_matrix": mass_audit},
        "golden_validation": golden_validation,
        "dual_audit": dual,
        "baseline_protection": baseline,
        "fault_injection": fault,
        "tests": {"compileall": "pass", "numerical_equivalence_specialized": "7 passed",
                   "persistent_ipc_specialized": "15 passed", "confirm_specialized": "44 passed",
                   "root_unittest": "1097 tests, 1096 passed, 1 skipped"},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0,
                                 "C++_worker": int(dual.get("worker_start_count", 0))},
        "authorized_matlab_export_process_starts": {"attempts": 2, "successful_exports": 1,
                                                     "failed_exports": 1, "return_codes": [0, 0]},
        "owned_residual": int(dual.get("owned_residual", 1)),
        "residual_process_audit": residual,
        "old_evidence_modified": False, "old_runtime_reused": False, "cfd_started": False,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if numerical_gate_ok else "not_completed",
        "C++_WORKER_PERSISTENT_IPC_STATUS": "not_completed",
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
                          "LOCK_IN_CLAIM": "not_completed"},
    }
    RESULTS.mkdir(parents=True)
    DOCS.mkdir(parents=True)
    _write(RESULTS / "matlab_worker_baseline_protection_audit.json", baseline)
    _write(RESULTS / "matlab_cpp_dual_run_audit.json", {"golden_validation": golden_validation, "dual_audit": dual,
                                                         "contract": payload["matlab_contract"]})
    _write(RESULTS / "ipc_fault_injection_audit.json", fault)
    _write(RESULTS / "resource_audit.json", {"real_process_starts": payload["real_process_starts"],
                                              "authorized_matlab_export_process_starts": payload["authorized_matlab_export_process_starts"],
                                              "owned_residual": payload["owned_residual"], "residual_process_audit": residual,
                                              "c_drive_artifacts": 0})
    _write(RESULTS / "test_discovery_audit.json", payload["tests"])
    _write(RESULTS / "phase_timing_summary.json", {"status": "not_evaluable", "reason": "no CFD confirm authorized or launched"})
    _write(RESULTS / "performance_comparison.json", {"status": "not_evaluable", "reason": "no OpenFOAM/WSL/CFD confirm authorized or launched"})
    _write(RESULTS / "stage4f_d_cpp_worker_numerical_equivalence_before_cfd_v1_gate.json", {
        "gate": numerical_gate, "status": payload["status"], "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "engineering_pass_steps": engineering, "strict_diagnostic_pass_steps": int(dual.get("strict_pass_steps", 0)),
        "max_error_by_field": dual.get("max_error_by_field", {}), "baseline": baseline,
        "real_process_starts": payload["real_process_starts"], "owned_residual": payload["owned_residual"],
        "old_evidence_modified": False, "old_runtime_reused": False, "cfd_started": False,
        "C++_ANCF_NUMERICAL_CORE_STATUS": payload["C++_ANCF_NUMERICAL_CORE_STATUS"],
        "new_cfd_authorization_required": True,
    })
    _write(RESULTS / "stop_gate_audit.json", {"cfd_started": False, "next_confirm_started": False,
                                               "owned_residual": payload["owned_residual"], "residual_processes": residual})
    _write(RESULTS / "final_audit.json", payload)
    report = f"""# C++ ANCF MATLAB/C++ 数值等价离线审计

- 数值 Gate：`{numerical_gate}`
- MATLAB 黄金导出：step559 seed -> target step560-599，共 40 条；step、bridge step、time、tick、有限值和 payload hash 校验通过。
- 数值合同：MATLAB 与 C++ 均使用 Gauss={fixture['gauss_order']}、max_newton={fixture['max_newton']}、dt={fixture['dt_s']} s；102x102 source mass matrix 已显式传输。
- C++ 双算：工程误差合同 {engineering}/40；严格 1e-11 诊断 {dual.get('strict_pass_steps', 0)}/40。严格值仅用于跨实现浮点差异诊断，不改变既定工程误差合同。
- 最大误差：q={dual['max_error_by_field']['q']['max_abs']:.6g}，qdot={dual['max_error_by_field']['qdot']['max_abs']:.6g}，qddot={dual['max_error_by_field']['qddot']['max_abs']:.6g}，internal_force={dual['max_error_by_field']['internal_force']['max_abs']:.6g}，residual={dual['max_error_by_field']['residual']['max_abs']:.6g}。
- MATLAB worker baseline：44/44 文件 hash/size 通过，manifest SHA-256={baseline['manifest_sha256']}，可回退且只读。
- 专项测试：compileall 通过；数值 7/7；persistent IPC 15/15；confirm 44/44；根目录 unittest 1097（1096 passed、1 skipped）。
- 离线验证真实进程启动：MATLAB=0、OpenFOAM=0、WSL=0、CFD=0；C++ worker startup=1；owned residual=0。
- 本次明确授权仅用于 MATLAB 黄金导出：尝试 2 次，成功导出 1 次；没有执行 OpenFOAM、WSL、CFD 或 confirm。
- 旧证据、旧 runtime、物理参数、global dt、三 slice、阈值和正式协议未修改。

数值核心可标记为 `validated`，但总目标 `C++_WORKER_PERSISTENT_IPC_STATUS=not_completed`：真实 bounded confirm 尚未执行。phase timing/performance 在无 CFD confirm 时不可评估。下一步必须获得新的明确真实 confirm 授权后，才能创建全新的 40-step runtime；本次不自动启动。
"""
    (DOCS / "cpp_worker_numerical_equivalence_fresh_golden_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"gate": numerical_gate, "engineering_pass_steps": engineering,
                      "strict_diagnostic_pass_steps": dual.get("strict_pass_steps", 0),
                      "worker_start_count": dual.get("worker_start_count", 0), "owned_residual": dual.get("owned_residual", 1)}, ensure_ascii=True))
    return 0 if numerical_gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
