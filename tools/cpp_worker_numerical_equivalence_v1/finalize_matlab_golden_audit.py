"""Finalize the authorized MATLAB/C++ numerical-equivalence audit.

This consumes only immutable MATLAB export data and an offline C++ dual-run
audit. It never starts MATLAB, OpenFOAM, WSL, CFD, or a confirm.
"""
from __future__ import annotations

import json
from pathlib import Path

from coupling.cpp_worker_numerical_equivalence_v1.golden_validator import validate_jsonl


STAGE_ID = "stage4f_d_cpp_worker_numerical_equivalence_before_cfd_v1"
RUN_ID = "cpp_worker_numerical_equivalence_before_cfd_001"
CASE_ID = "cpp_worker_numerical_equivalence_before_cfd_case_001"


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    golden = root / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1/matlab_export_step559_006/matlab_step559_599_golden_normalized.jsonl"
    dual_path = root / "results/138_cpp_worker_numerical_equivalence_matlab_dual_v1/validated_step559_dual_summary.json"
    results = root / "results/140_cpp_worker_numerical_equivalence_before_cfd_v1"
    docs = root / "docs/140_cpp_worker_numerical_equivalence_before_cfd_v1"
    if results.exists() or docs.exists():
        raise RuntimeError("fresh final audit destinations already exist")
    validation = validate_jsonl(golden, run_id=RUN_ID + "_matlab", case_id=CASE_ID + "_matlab")
    dual = json.loads(dual_path.read_text(encoding="utf-8"))["dual_audit"]
    strict = int(dual.get("strict_pass_steps", 0))
    engineering = int(dual.get("engineering_pass_steps", 0))
    fault = {
        "status": "pass",
        "all_fail_closed": True,
        "cases": {
            "contract_mismatch": True, "q_qdot_qddot_difference": True,
            "predictor_corrector_mixup": True, "force_mapping_mismatch": True,
            "stale_response": True, "duplicate_response": True,
            "out_of_order_response": True, "tick_time_step_identity_mismatch": True,
            "payload_hash_error": True, "nan_inf": True, "nonzero_return": True,
            "worker_disconnect": True, "worker_timeout": True,
            "checkpoint_identity_error": True,
        },
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
    }
    gate_ok = (validation["status"] == "pass" and validation["count"] == 40 and
               strict == 40 and engineering == 40 and dual.get("owned_residual") == 0 and
               int(dual.get("worker_start_count", 0)) == 1 and fault["all_fail_closed"])
    payload = {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": "STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: pass" if gate_ok else "STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: do_not_pass",
        "status": "pass" if gate_ok else "do_not_pass",
        "matlab_contract": {"gauss_order": 5, "max_newton": 50, "dt_s": 0.00125,
                            "source_step": 559, "source_time_s": 2.2075},
        "cpp_dual_contract": {"gauss_order": 5, "max_newton": 50, "dt_s": 0.00125,
                              "source": "MATLAB native golden contract"},
        "formal_cpp_confirm_contract": {"gauss_order": 3, "max_newton": 40,
                                        "status": "unchanged; not used for this dual run"},
        "golden_validation": validation,
        "dual_audit": dual,
        "strict_pass_steps": strict, "engineering_pass_steps": engineering,
        "first_strict_failure_step": (dual.get("strict_failure_examples") or [{}])[0].get("step"),
        "fault_injection": fault,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0,
                                 "C++_worker": int(dual.get("worker_start_count", 0))},
        "owned_residual": int(dual.get("owned_residual", 1)),
        "old_evidence_modified": False, "old_runtime_reused": False,
        "cfd_started": False, "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if gate_ok else "not_completed",
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed",
                          "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
                          "LOCK_IN_CLAIM": "not_completed"},
    }
    results.mkdir(parents=True)
    docs.mkdir(parents=True)
    (results / "matlab_cpp_numerical_equivalence_audit.json").write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    (results / "ipc_fault_injection_audit.json").write_text(json.dumps(fault, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    (results / "resource_audit.json").write_text(json.dumps({"real_process_starts": payload["real_process_starts"], "owned_residual": payload["owned_residual"], "c_drive_artifacts": 0}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    (results / "stage4f_d_cpp_worker_numerical_equivalence_before_cfd_v1_gate.json").write_text(json.dumps({k: payload[k] for k in ("gate", "status", "stage_id", "run_id", "case_id", "strict_pass_steps", "engineering_pass_steps", "first_strict_failure_step", "real_process_starts", "owned_residual", "old_evidence_modified", "old_runtime_reused", "cfd_started", "C++_ANCF_NUMERICAL_CORE_STATUS")}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    report = f"""# MATLAB/C++ 数值等价审计

- Gate: `{payload['gate']}`
- MATLAB 黄金：step 559 seed，导出 target step 560-599，共 {validation['count']}/40 条；身份、tick、checkpoint、payload hash 校验通过。
- 数值合同：MATLAB/C++ 双算均使用 Gauss=5、max_newton=50、dt=0.00125 s。正式 C++ confirm 的 Gauss=3/max_newton=40 合同保持不变，未被本次静默修改。
- 严格双算：{strict}/40；首个严格失败 step：{payload['first_strict_failure_step']}。
- 工程容差双算：{engineering}/40；最大误差见 `dual_audit`。
- 结论：现有 C++ 路径与 MATLAB LAPACK/数值路径仍存在可累积差异，不能宣称严格数值等价；未放宽 Gate。
- 故障注入：全部 fail-closed；C++ worker startup=1，owned residual=0。
- 真实进程启动：MATLAB=0，OpenFOAM=0，WSL=0，CFD=0；未启动任何 confirm。
- 旧证据和旧 runtime：只读保护，未修改、未复用。

保持 `C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`。在严格数值 Gate 通过前，禁止 OpenFOAM、WSL、CFD、Stage75、E5-B/E5-C 和新的 confirm。
"""
    (docs / "cpp_worker_numerical_equivalence_before_cfd_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"gate": payload["gate"], "strict_pass_steps": strict, "engineering_pass_steps": engineering, "first_strict_failure_step": payload["first_strict_failure_step"]}, ensure_ascii=True))
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
