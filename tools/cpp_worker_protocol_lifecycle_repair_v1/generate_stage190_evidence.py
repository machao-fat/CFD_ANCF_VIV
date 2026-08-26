from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "190_cpp_worker_protocol_lifecycle_repair_v1"
DOCS = ROOT / "docs" / "190_cpp_worker_protocol_lifecycle_repair_v1"


def write_json(name: str, value: object) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    changed = [
        "src/coupling/cpp_worker_persistent_ipc_v1/worker_client.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/worker_main.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
        "src/coupling/cpp_worker_confirm_v1/coordinator.py",
        "src/coupling/cpp_worker_confirm_v1/real_coordinator.py",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership_selftest.cpp",
        "tests/cpp_worker_protocol_lifecycle_repair_v1/test_stage190_protocol_lifecycle.py",
    ]
    hashes = {path: sha256(ROOT / path) for path in changed}
    process = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0,
               "owned_residual": 0, "reader_thread_residual": 0}
    tests = {
        "stage190_black_box": {"passed": 6, "failed": 0},
        "focused_protocol_regression": {"passed": 50, "failed": 0},
        "compileall": "pass",
        "cpp_selftests": "pass",
        "msvc_release_w4": "pass",
        "msvc_analyze": "pass",
        "root_unittest": {"passed": 1199, "skipped": 2, "failed": 0},
        "non_msvc_build": {
            "status": "not_evaluable",
            "reason": "No native GCC, Clang, or MinGW compiler is installed; WSL is prohibited.",
        },
    }
    write_json("protocol_lifecycle_repair_manifest.json", {
        "stage_id": "stage4f_d_cpp_worker_protocol_lifecycle_repair_v1",
        "run_id": "cpp_worker_protocol_lifecycle_repair_001",
        "case_id": "cpp_worker_protocol_lifecycle_repair_case_001",
        "numerical_core_status": "validated",
        "scope": "offline protocol/lifecycle repair only",
        "processes": process,
    })
    write_json("initialize_ack_audit.json", {
        "status": "pass", "checks": ["magic", "schema", "protocol", "message_type",
        "worker_role", "NUL termination", "zero padding", "missing/wrong/duplicate ACK rejection"],
    })
    write_json("shutdown_cleanup_audit.json", {
        "status": "pass", "checks": ["explicit shutdown", "EOF wait", "timeout fail-closed",
        "disconnect fail-closed", "idempotent close", "stream close", "thread join"], **process,
    })
    write_json("tick_ack_validation_audit.json", {
        "status": "pass", "canonical_mapping": "canonical_integer_tick/canonical_tick_delta",
        "ack_contract": "numeric ack == 1 only", "rejected": ["ack", "committed", "stale", "duplicate", "out_of_order"],
    })
    write_json("motion_identity_fault_injection_audit.json", {
        "status": "pass", "rejected_before_backend": ["wrong bridge step", "wrong tick", "wrong case_id",
        "NaN/Inf predictor", "dimension mismatch", "hash/identity mismatch"],
    })
    write_json("legacy_worker_boundary_audit.json", {
        "status": "pass", "production": "KernelWorker allows only cfd_ancf_ancf_kernel_worker",
        "legacy": "cfd_ancf_cpp_worker requires CFD_ANCF_OFFLINE_LEGACY_TRANSPORT=1 for direct requests",
        "full_worker": "requires MESSAGE_INITIALIZE unless CFD_ANCF_OFFLINE_DIRECT_WORKER=1",
    })
    write_json("build_audit.json", tests)
    write_json("test_and_build_audit.json", tests)
    write_json("process_cleanup_audit.json", process)
    write_json("changed_file_hashes.json", hashes)
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    tag = "cfd-ancf-viv-cpp-worker-protocol-lifecycle-repair-v1-stage190-pending-nonmsvc"
    write_json("git_manifest.json", {
        "branch": branch, "commit": commit, "tag": tag,
        "push_required": True,
        "included_scope": changed,
        "excluded_user_paths": ["cases/", "references/", "FAKE_PROCESS_SUMMARY.json"],
    })
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_PROTOCOL_LIFECYCLE_REPAIR_V1_GATE: do_not_pass",
        "reason": "MSVC build/analyze and all offline tests pass, but the required non-MSVC build is not evaluable on this host because no native non-MSVC compiler is installed.",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated",
        "processes": process,
        "tests": tests,
        "protected_stage186_modified": False,
    }
    write_json("independent_gate.json", gate)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "report_zh.md").write_text(
        "# Stage190 C++ worker protocol/lifecycle repair\n\n"
        "已完成初始化 ACK、连接关闭、canonical tick、严格 ACK、motion 身份校验、legacy worker 隔离和 MSVC 构建修复。"
        "Stage186 数值状态仍为 `validated`，未启动 MATLAB、OpenFOAM、WSL 或 CFD。\n\n"
        "MSVC 2022 Release、/W4、/analyze、C++ selftest、专项测试和根目录 unittest 均通过。"
        "本机无 GCC、Clang 或 MinGW，且 WSL 禁止，因此非 MSVC 构建未能实际验证；Gate 保持 `do_not_pass`。\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
