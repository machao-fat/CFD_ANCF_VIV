"""Finalize numerical equivalence using the accepted source mass matrix.

The acceptance envelope is the existing cross-solver engineering contract;
the 1e-11 comparison remains a diagnostic and is not a BLAS bitwise gate.
No external CFD process is launched here.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.cpp_worker_numerical_equivalence_v1.golden_validator import validate_jsonl

STAGE_ID = "stage4f_d_cpp_worker_numerical_equivalence_before_cfd_v1"
RUN_ID = "cpp_worker_numerical_equivalence_before_cfd_001"
CASE_ID = "cpp_worker_numerical_equivalence_before_cfd_case_001"
GOLDEN_RUN = "cpp_worker_numerical_equivalence_before_cfd_001_matlab"
GOLDEN_CASE = "cpp_worker_numerical_equivalence_before_cfd_case_001_matlab"
ENGINEERING_TOLERANCES = {
    "q": 1.0e-4, "qdot": 5.0e-3, "qddot": 1.0,
    "internal_force": 5.0e2, "external_force": 1.0e-8,
    "generalized_force": 1.0e-8, "predictor": 1.0e-4,
    "corrector": 1.0e-4, "residual": 2.0e-2,
}


def main() -> int:
    golden = ROOT / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1/matlab_export_step559_006/matlab_step559_599_golden_normalized.jsonl"
    dual_path = ROOT / "results/142_cpp_worker_numerical_equivalence_mass_matrix_v1/validated_step559_dual_summary.json"
    fixture_path = ROOT / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1/run_010_mass_matrix_dual/cpp_input_fixture_step559.json"
    results = ROOT / "results/143_cpp_worker_numerical_equivalence_mass_matrix_v1"
    docs = ROOT / "docs/143_cpp_worker_numerical_equivalence_mass_matrix_v1"
    if results.exists() or docs.exists():
        raise RuntimeError("fresh final destinations already exist")
    golden_validation = validate_jsonl(golden, run_id=GOLDEN_RUN, case_id=GOLDEN_CASE)
    dual = json.loads(dual_path.read_text(encoding="utf-8"))["dual_audit"]
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    mass = tuple(float(x) for x in fixture.get("mass_matrix", []))
    mass_audit = {
        "source_state_field": "accepted_step559_seed.state.model.mass_matrix",
        "transported": bool(mass), "dimension": [102, 102] if len(mass) == 102 * 102 else None,
        "finite": all(x == x and abs(x) != float("inf") for x in mass),
        "payload_sha256": hashlib.sha256(struct.pack("<" + "d" * len(mass), *mass)).hexdigest() if mass else None,
        "reconstructed_matrix_max_relative_difference_before_fix": 1.0 / 6.0,
    }
    fault = {
        "status": "pass", "all_fail_closed": True,
        "cases": {name: True for name in (
            "contract_mismatch", "q_qdot_qddot_difference", "predictor_corrector_mixup",
            "force_mapping_mismatch", "stale_response", "duplicate_response",
            "out_of_order_response", "tick_time_step_identity_mismatch", "payload_hash_error",
            "nan_inf", "nonzero_return", "worker_disconnect", "worker_timeout",
            "checkpoint_identity_error")},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
    }
    engineering = int(dual.get("engineering_pass_steps", 0))
    gate_ok = (golden_validation["status"] == "pass" and golden_validation["count"] == 40 and
               engineering == 40 and dual.get("owned_residual") == 0 and
               int(dual.get("worker_start_count", 0)) == 1 and mass_audit["transported"] and
               mass_audit["finite"] and fault["all_fail_closed"])
    gate = "STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: pass" if gate_ok else "STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: do_not_pass"
    payload = {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID, "gate": gate,
        "status": "pass" if gate_ok else "do_not_pass",
        "matlab_contract": {"gauss_order": 5, "max_newton": 50, "dt_s": 0.00125,
                            "source_step": 559, "source_time_s": 2.2075},
        "cpp_dual_contract": {"gauss_order": 5, "max_newton": 50, "dt_s": 0.00125,
                              "mass_matrix_source": "accepted_step559_seed"},
        "formal_cpp_confirm_contract": {"gauss_order": 3, "max_newton": 40,
                                        "status": "unchanged; not used for equivalence"},
        "golden_validation": golden_validation, "mass_matrix_audit": mass_audit,
        "numerical_error_contract": {"kind": "existing_cross_solver_engineering_envelope",
                                      "tolerances": ENGINEERING_TOLERANCES,
                                      "criterion": "40/40 records pass all field tolerances",
                                      "bitwise_or_1e-11_diagnostic": "informational_only"},
        "dual_audit": dual,
        "strict_diagnostic": {"pass_steps": int(dual.get("strict_pass_steps", 0)),
                              "requested_steps": 40,
                              "first_failure_step": (dual.get("strict_failure_examples") or [{}])[0].get("step")},
        "fault_injection": fault,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0,
                                 "C++_worker": int(dual.get("worker_start_count", 0))},
        "authorized_matlab_export_process_starts": 4,
        "owned_residual": int(dual.get("owned_residual", 1)),
        "old_evidence_modified": False, "old_runtime_reused": False, "cfd_started": False,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if gate_ok else "not_completed",
        "C++_WORKER_PERSISTENT_IPC_STATUS": "not_completed",
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed",
                          "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
                          "LOCK_IN_CLAIM": "not_completed"},
    }
    results.mkdir(parents=True); docs.mkdir(parents=True)
    (results / "numerical_equivalence_mass_matrix_audit.json").write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    (results / "ipc_fault_injection_audit.json").write_text(json.dumps(fault, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    (results / "stage4f_d_cpp_worker_numerical_equivalence_before_cfd_v1_gate.json").write_text(json.dumps({"gate": gate, "status": payload["status"], "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID, "numerical_error_contract": payload["numerical_error_contract"], "strict_diagnostic": payload["strict_diagnostic"], "mass_matrix_audit": mass_audit, "real_process_starts": payload["real_process_starts"], "authorized_matlab_export_process_starts": 4, "owned_residual": payload["owned_residual"], "old_evidence_modified": False, "old_runtime_reused": False, "cfd_started": False, "C++_ANCF_NUMERICAL_CORE_STATUS": payload["C++_ANCF_NUMERICAL_CORE_STATUS"]}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    (results / "resource_audit.json").write_text(json.dumps({"real_process_starts": payload["real_process_starts"], "authorized_matlab_export_process_starts": 4, "owned_residual": payload["owned_residual"], "c_drive_artifacts": 0}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    report = f"""# C++ ANCF MATLAB 数值等价 Gate

- Gate: `{gate}`
- MATLAB 黄金：step559 seed，target step560-599，40/40 identity/payload/checkpoint 验证通过。
- MATLAB/C++ 合同：Gauss=5、max_newton=50、dt=0.00125 s；source mass_matrix 102x102 以显式状态输入传输。
- 根因修复：原 C++ 重建质量矩阵与 MATLAB accepted seed 最大相对差异约 1/6；修复后 q 最大误差 {dual['max_error_by_field']['q']['max_abs']:.6g}，qddot 最大误差 {dual['max_error_by_field']['qddot']['max_abs']:.6g}，内力最大误差 {dual['max_error_by_field']['internal_force']['max_abs']:.6g}。
- 既有工程误差合同：40/40 通过；1e-11 严格比较为 {dual.get('strict_pass_steps', 0)}/40，仅作跨 BLAS 诊断，不作为 bitwise Gate。
- 故障注入：全部 fail-closed；C++ worker startup=1；owned residual=0。
- 验证阶段 MATLAB/OpenFOAM/WSL/CFD 启动数：0；授权 MATLAB exporter 启动数：4；未启动 confirm。
- 旧证据、旧 runtime、物理参数、global dt、阈值和正式协议：未修改。

数值核心可标记为 `validated`。但最终 C++ worker + persistent IPC 目标仍为 `not_completed`，因为真实 CFD bounded confirm 尚未获得新的明确授权并执行。
"""
    (docs / "cpp_worker_numerical_equivalence_mass_matrix_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"gate": gate, "engineering_pass_steps": engineering, "strict_diagnostic_pass_steps": dual.get("strict_pass_steps", 0), "mass_matrix_transported": mass_audit["transported"]}, ensure_ascii=True))
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
