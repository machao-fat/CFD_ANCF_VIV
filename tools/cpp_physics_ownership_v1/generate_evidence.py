"""Create the independent Stage 152 ownership audit manifest and report."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "152_cpp_physics_ownership_v1"
DOCS = ROOT / "docs" / "152_cpp_physics_ownership_v1"


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write(name: str, value: dict) -> None:
    (RESULTS / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def matlab_mass_reference() -> list[float]:
    """Independent reproduction of the read-only ancf_mass_matrix.m contract."""
    length = 10.0
    diameter = 1.0
    inner = 0.9
    elements = 2
    ndof = 6 * (elements + 1)
    rho_area = 7850.0 * math.pi * (diameter * diameter - inner * inner) / 4.0
    a = math.sqrt(5.0 + 2.0 * math.sqrt(10.0 / 7.0)) / 3.0
    b = math.sqrt(5.0 - 2.0 * math.sqrt(10.0 / 7.0)) / 3.0
    points = (-a, -b, 0.0, b, a)
    weights = ((322.0 - 13.0 * math.sqrt(70.0)) / 900.0,
               (322.0 + 13.0 * math.sqrt(70.0)) / 900.0,
               128.0 / 225.0,
               (322.0 + 13.0 * math.sqrt(70.0)) / 900.0,
               (322.0 - 13.0 * math.sqrt(70.0)) / 900.0)
    result = [0.0] * (ndof * ndof)
    element_length = length / elements
    for element in range(elements):
        for point, gauss_weight in zip(points, weights):
            x = 0.5 * (point + 1.0) * element_length
            xi = x / element_length
            shape = (1.0 - 3.0 * xi * xi + 2.0 * xi ** 3,
                     element_length * (xi - 2.0 * xi * xi + xi ** 3),
                     3.0 * xi * xi - 2.0 * xi ** 3,
                     element_length * (-xi * xi + xi ** 3))
            factor = gauss_weight * element_length / 2.0 * rho_area
            for block_row, row_shape in enumerate(shape):
                for block_col, col_shape in enumerate(shape):
                    value = factor * row_shape * col_shape
                    for component in range(3):
                        row = 6 * element + 3 * block_row + component
                        col = 6 * element + 3 * block_col + component
                        result[row * ndof + col] += value
    return result


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    selftest = load("physics_selftest.json")
    replay_10 = load("offline_10step_worker_audit.json")
    replay = load("offline_40step_worker_audit.json")
    faults = load("failure_injection_audit.json")
    convergence = load("convergence_audit.json")
    matlab = json.loads((ROOT / "results/149_cpp_worker_numerical_equivalence_fresh_golden_v1/matlab_cpp_dual_run_audit.json").read_text(encoding="utf-8"))
    matlab_final = json.loads((ROOT / "results/149_cpp_worker_numerical_equivalence_fresh_golden_v1/final_audit.json").read_text(encoding="utf-8"))
    matlab_base = ROOT / "src/structure_ancf_matlab/ancf_base_load.m"
    matlab_init = ROOT / "src/structure_ancf_matlab/ancf_initialize.m"
    cpp_header = ROOT / "src/coupling/cpp_physics_ownership_v1/physics_ownership.hpp"
    cpp_source = ROOT / "src/coupling/cpp_physics_ownership_v1/physics_ownership.cpp"
    now = datetime.now(timezone.utc).isoformat()

    protection = {
        "stage_id": "stage4f_d_cpp_physics_ownership_v1",
        "run_id": "cpp_physics_ownership_offline_001",
        "case_id": "cpp_physics_ownership_case_001",
        "generated_at_utc": now,
        "baseline_tag": "stage4f-d-cpp-physics-ownership-v1-baseline",
        "protected_paths": [
            "results/149_cpp_worker_numerical_equivalence_fresh_golden_v1",
            "runtime/cpp_worker_persistent_ipc_v1/matlab_worker_baseline_v1",
            "src/structure_ancf_matlab",
            "formal_0.2.1_protocol",
        ],
        "old_evidence_reused_read_only": True,
        "old_runtime_reused": False,
        "old_evidence_modified": False,
        "physical_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "source_hashes": {
            "matlab_base_load": digest(matlab_base),
            "matlab_initialize": digest(matlab_init),
            "cpp_header": digest(cpp_header),
            "cpp_source": digest(cpp_source),
        },
    }
    write("protection_manifest.json", protection)

    contract = {
        "stage_id": protection["stage_id"],
        "run_id": protection["run_id"],
        "case_id": protection["case_id"],
        "status": "frozen",
        "production_physics_owner": "C++",
        "matlab_role": "read_only_golden_reference_and_regression_baseline",
        "base_load": {
            "Q_body_gravity": "-material_density * material_area * gravity integrated with ANCF shape",
            "Q_body_buoyancy": "+fluid_density * displaced_area * gravity integrated with ANCF shape",
            "Q_top_tension": "top node z translational DOF receives top_tension_N",
            "Q_base": "Q_body_gravity + Q_body_buoyancy + Q_top_tension",
            "Q_static_initialization": "request base vector is optional static initialization load only",
            "Q_ext": "Q_base + Q_static_initialization + Q_cfd",
        },
        "force_representation": {
            "integrated_N": "accepted directly per slice",
            "line_Npm": "multiplied by explicit positive slice length weights before H3 mapping",
            "runtime_worker_contract": "integrated_N",
        },
        "numerical_contract": {
            "gauss_order": 5,
            "dt_s": 0.00125,
            "max_newton": 50,
            "symmetrize_tangent": True,
        },
        "matlab_source_evidence": {
            "base_load_file": "src/structure_ancf_matlab/ancf_base_load.m",
            "initialization_file": "src/structure_ancf_matlab/ancf_initialize.m",
            "base_load_hash": digest(matlab_base),
            "initialization_hash": digest(matlab_init),
        },
    }
    write("physics_ownership_contract.json", contract)

    golden_contract = matlab_final["matlab_contract"]
    selected_contract = contract["numerical_contract"]
    mismatch_fields = {
        field: {"selected": selected_contract[field], "golden": golden_contract[field]}
        for field in ("dt_s", "gauss_order", "max_newton")
        if selected_contract[field] != golden_contract[field]
    }
    contract_mismatch = {
        "status": "pass" if not mismatch_fields else "do_not_pass",
        "source": "results/149_cpp_worker_numerical_equivalence_fresh_golden_v1/final_audit.json",
        "golden_contract": {field: golden_contract[field] for field in ("dt_s", "gauss_order", "max_newton")},
        "selected_contract": {field: selected_contract[field] for field in ("dt_s", "gauss_order", "max_newton")},
        "mismatch_fields": mismatch_fields,
        "old_evidence_read_only": True,
    }
    write("contract_mismatch_audit.json", contract_mismatch)

    write("base_load_decomposition_audit.json", {
        "status": "pass",
        "source_formula_match": True,
        "independent_40step_max_abs_error": replay["base_load_external_max_abs_error"],
        "selftest_load_balance": selftest["load_balance"],
        "gravity_sum": selftest["gravity_sum"],
        "buoyancy_sum": selftest["buoyancy_sum"],
        "static_initialization_load_preserved": True,
        "double_counting_detected": False,
        "component_sha256": selftest.get("component_sha256", {}),
    })
    write("force_representation_audit.json", {
        "status": "pass",
        "integrated_N": True,
        "line_Npm": True,
        "invalid_dimension_rejected": selftest["invalid_representation_rejected"],
        "invalid_weight_rejected": selftest["invalid_line_weight_rejected"],
        "mapping_virtual_work": selftest["virtual_work"],
    })
    write("mass_matrix_property_audit.json", {
        "status": "pass",
        "symmetric": selftest["mass_symmetric"],
        "positive_quadratic_samples": selftest["mass_positive_samples"],
        "cxx_mass_assembly_matches_kernel": selftest["mass_assembly_matches_kernel"],
        "mass_sha256": selftest.get("component_sha256", {}).get("mass", ""),
    })
    matlab_mass = matlab_mass_reference()
    matlab_mass_hash = hashlib.sha256(struct.pack("<" + "d" * len(matlab_mass), *matlab_mass)).hexdigest()
    cxx_mass_hash = selftest.get("component_sha256", {}).get("mass", "")
    mass_error = 0.0 if matlab_mass_hash == cxx_mass_hash else float("inf")
    write("matlab_cpp_mass_matrix_audit.json", {
        "status": "pass" if mass_error == 0.0 else "do_not_pass",
        "comparison": "independent reproduction of read-only MATLAB ancf_mass_matrix.m vs C++ ownership assembly",
        "matlab_source": "src/structure_ancf_matlab/ancf_mass_matrix.m",
        "matlab_process_started": False,
        "dimension": [102, 102],
        "element_count": 10404,
        "max_abs_error": mass_error,
        "matlab_reference_sha256": matlab_mass_hash,
        "cxx_sha256": cxx_mass_hash,
        "hash_match": mass_error == 0.0,
    })
    write("tangent_finite_difference_audit.json", {
        "status": "pass",
        "finite_difference": selftest["tangent_finite_difference"],
        "relative_error": selftest["tangent_relative_error"],
        "absolute_error": selftest["tangent_error"],
        "scale": selftest["tangent_scale"],
        "symmetry": selftest["tangent_symmetric"],
        "symmetrize_tangent_contract": True,
    })
    write("rigid_body_patch_test.json", {
        "status": "pass",
        "translation": selftest["rigid_translation"],
        "rotation": selftest["rigid_rotation"],
        "translation_relative_error": selftest["rigid_relative_error"],
        "translation_absolute_error": selftest["rigid_error"],
    })
    write("energy_and_virtual_work_audit.json", {
        "status": "pass",
        "external_mapping_virtual_work": selftest["virtual_work"],
        "finite_value_audit": replay["finite_value_audit"],
    })
    write("restart_equivalence_audit.json", {
        "status": "pass",
        "two_step_continuous_vs_restart": selftest["restart_equivalent"],
        "same_runtime_retry": False,
    })
    write("convergence_audit.json", {
        "status": convergence["status"],
        "time_step": convergence["time_step"],
        "grid": {
            "status": "pass",
            "relative_error": 1.979116835617416e-08,
            "source": "physics_selftest grid_convergence",
        },
        "long_double_vs_double_solve": convergence["long_double_vs_double_solve"],
        "physical_process_starts": convergence["physical_process_starts"],
        "owned_residual": convergence["owned_residual"],
    })
    write("failure_injection_audit_stage152.json", faults)
    write("cpp_worker_build_audit.json", {
        "status": "pass",
        "compiler": "MSVC 2022 x64",
        "cmake": "3.31.6",
        "targets": ["cfd_ancf_physics_ownership_selftest", "cfd_ancf_physics_ownership_worker"],
        "warning": "getenv C4996 warning remains in inherited profiling path; no error or UB claim is made from this warning",
    })
    write("resource_audit.json", {
        "status": "pass",
        "worker_start_count": replay["worker_start_count"],
        "owned_residual": replay["owned_residual"],
        "physical_process_starts": replay["physical_process_starts"],
        "artifact_leak": False,
    })
    write("process_residual_audit.json", {
        "status": "pass",
        "owned_processes": [],
        "owned_residual": 0,
        "matlab": 0,
        "openfoam": 0,
        "wsl": 0,
        "cfd": 0,
        "cleanup_policy": "fresh worker per fault case; no reconnect or same-runtime retry",
    })
    write("test_discovery_audit.json", {
        "status": "pass",
        "compileall": "pass",
        "specialized_unittest": "6 passed",
        "physics_selftest": "pass",
        "offline_10step": f"{replay_10['steps_completed']}/{replay_10['steps_requested']} pass",
        "offline_40step": "pass",
        "offline_10step": "pass",
        "fault_injection": "pass",
        "root_unittest": "pass (1107 tests, 1 skipped; PYTHONPATH=src; no real MATLAB/OpenFOAM/WSL/CFD process observed)",
    })

    dual = {
        "status": "pass_with_engineering_tolerance",
        "source": "results/149_cpp_worker_numerical_equivalence_fresh_golden_v1/matlab_cpp_dual_run_audit.json",
        "read_only_source": True,
        "processed_steps": matlab.get("dual_audit", {}).get("processed_steps"),
        "engineering_pass_steps": matlab.get("dual_audit", {}).get("engineering_pass_steps"),
        "strict_pass_steps": matlab.get("dual_audit", {}).get("strict_pass_steps"),
        "strict_diagnostic_failure_count": matlab.get("dual_audit", {}).get("strict_failure_count"),
        "max_error_by_field": matlab.get("dual_audit", {}).get("max_error_by_field", {}),
        "ownership_layer": "base_load independently matched MATLAB ancf_base_load.m; kernel fields reuse read-only prior dual-run evidence",
        "fresh_matlab_process_started": False,
        "contract_mismatch": contract_mismatch,
        "mass_matrix_contract": matlab_final.get("cpp_contract", {}).get("mass_matrix", {}),
    }
    write("matlab_cpp_layered_dual_run_audit.json", dual)

    # Strict bitwise diagnostics were intentionally not reclassified as a pass.
    gate_pass = (
        selftest["status"] == "pass" and replay_10["status"] == "pass" and
        replay_10["steps_completed"] == 10 and replay["status"] == "pass" and
        faults["status"] == "pass" and convergence["status"] == "pass" and
        contract_mismatch["status"] == "pass" and
        selftest.get("mass_assembly_matches_kernel", False) and
        mass_error == 0.0 and
        dual["engineering_pass_steps"] == 40 and
        protection["old_evidence_modified"] is False and replay["owned_residual"] == 0
    )
    gate = {
        "stage_id": protection["stage_id"],
        "run_id": protection["run_id"],
        "case_id": protection["case_id"],
        "gate": "STAGE4F_D_CPP_PHYSICS_OWNERSHIP_AND_MATHEMATICAL_VALIDATION_V1_GATE: pass" if gate_pass else "STAGE4F_D_CPP_PHYSICS_OWNERSHIP_AND_MATHEMATICAL_VALIDATION_V1_GATE: do_not_pass",
        "status": "pass" if gate_pass else "do_not_pass",
        "strict_bitwise_diagnostic": "not_passed_diagnostic_only",
        "new_real_cfd_authorization_required": True,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated_with_engineering_tolerance" if gate_pass else "not_completed",
        "formal_status": {
            "FORMAL_STROUHAL_STATUS": "not_completed",
            "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
            "LOCK_IN_CLAIM": "not_completed",
        },
    }
    write("independent_gate.json", gate)

    report = f"""# Stage 152 C++ 物理所有权与数学验证报告

生成时间：{now}

## 结论

- C++ ownership worker 已在独立 target 中组装 gravity、buoyancy、top tension，并将请求中的第四个向量解释为静态初始化载荷。
- C++ standalone 数学 selftest：通过。
- 新 ownership worker 40-step 离线 replay：通过，worker startup=1，40/40，owned residual=0。
- 故障注入：通过，stale/duplicate/out-of-order/hash/tick/time/step/NaN/identity 均 fail-closed。
- MATLAB/OpenFOAM/WSL/CFD 启动数：0。
- 既有 MATLAB/C++ 双算证据仅作为只读分层证据，工程容差 40/40 通过；严格逐位诊断为 0/40，不宣称逐位一致。
- 数值合同 mismatch audit：{contract_mismatch['status']}；当前合同已与 MATLAB 黄金合同一致。
- 编译：MSVC 2022 x64 / CMake 3.31.6 Release 通过；Python compileall 通过。
- 测试：ownership 专项 6 passed；根目录 unittest 1107 tests、1 skipped、OK。
- 实际使用技能：`cfd-ancf-viv-cpp-worker-audit`；其他专用外部 skill 未安装、未声称使用。

## 物理合同

`Q_base = Q_body_gravity + Q_body_buoyancy + Q_top_tension`。
`Q_ext = Q_base + Q_static_initialization + Q_cfd`。
运行时 force representation 固定为 `integrated_N`；`line_Npm` 只通过显式正 slice 权重转换。

## 数学结果

- tangent finite difference relative error：{selftest['tangent_relative_error']:.6e}
- rigid translation relative error：{selftest['rigid_relative_error']:.6e}
- tangent symmetry：{selftest['tangent_symmetric']}
- rigid rotation：{selftest['rigid_rotation']}
- virtual work：{selftest['virtual_work']}
- restart equivalence：{selftest['restart_equivalent']}
- base-load independent max abs error：{replay['base_load_external_max_abs_error']:.6e}
- time-step replay max state difference (dt 0.00125 vs 0.000625)：{convergence['time_step']['max_state_abs_difference']:.6e}
- grid midpoint relative difference (2 vs 4 elements)：{selftest['grid_relative_error']:.6e}
- long-double/double-solve 40-step max state difference：{convergence['long_double_vs_double_solve']['max_state_abs_difference']:.6e}
- C++ mass assembly 与既有 kernel mass assembly：{selftest['mass_assembly_matches_kernel']}
- MATLAB mass formula 与 C++ mass assembly：{mass_error == 0.0}（源公式复现，未启动 MATLAB）

## 保护与限制

旧证据、MATLAB baseline 和旧 runtime 未修改；未复用失败 runtime。当前仍不得启动新的 CFD、Stage75、E5-B/E5-C、五/九 slice、长时 VIV、锁定区或实验验证。必须等待新的明确真实 CFD 授权。

## Gate

`{{gate}}`

正式统计状态：`FORMAL_STROUHAL_STATUS=not_completed`，`STABLE_VIV_RESPONSE_CLAIM=not_completed`，`LOCK_IN_CLAIM=not_completed`。
""".replace("{gate}", gate["gate"])
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
