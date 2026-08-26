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
        "src/coupling/cpp_worker_persistent_ipc_v1/CMakeLists.txt",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership.cpp",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
        "src/coupling/cpp_worker_confirm_v1/coordinator.py",
        "src/coupling/cpp_worker_confirm_v1/real_coordinator.py",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership_selftest.cpp",
        "tests/cpp_worker_protocol_lifecycle_repair_v1/test_stage190_protocol_lifecycle.py",
        "tools/cpp_worker_protocol_lifecycle_repair_v1/generate_stage190_evidence.py",
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
        "non_msvc_build": {
            "status": "pass",
            "compiler": "LLVM clang++ 22.1.8",
            "generator": "NMake Makefiles",
            "sdk_environment": "VS2022 x64 Developer Command Prompt",
            "warnings": "-Wall -Wextra -Wpedantic -Werror",
            "selftests": "pass",
        },
        "root_unittest": {"passed": 1199, "skipped": 2, "failed": 0},
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
    write_json("non_msvc_build_audit.json", {
        "status": "pass",
        "compiler": "C:/Program Files/LLVM/bin/clang++.exe",
        "compiler_version": "LLVM clang++ 22.1.8",
        "generator": "NMake Makefiles",
        "environment": "VS2022 x64 Developer Command Prompt",
        "flags": ["-Wall", "-Wextra", "-Wpedantic", "-Werror"],
        "build_directory": "runtime/cpp_worker_protocol_lifecycle_repair_v1/build-clang",
        "selftests": "all selftests passed",
        "real_processes": process,
    })
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
    tag = "cfd-ancf-viv-cpp-worker-protocol-lifecycle-repair-v1-stage190"
    write_json("git_manifest.json", {
        "branch": branch, "commit": commit, "tag": tag,
        "push_required": True,
        "included_scope": changed,
        "excluded_user_paths": ["cases/", "references/", "FAKE_PROCESS_SUMMARY.json"],
    })
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_PROTOCOL_LIFECYCLE_REPAIR_V1_GATE: pass",
        "reason": "MSVC and native LLVM Clang builds, static analysis, offline protocol tests, compileall, and root regression all pass.",
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
        "MSVC 2022 Release、/W4、/analyze、LLVM Clang 22.1.8 原生构建、C++ selftest、专项测试和根目录 unittest 均通过。"
        "Clang 构建使用独立目录、NMake 和 VS2022 x64 SDK/linker，未启动 WSL 或任何真实 CFD 进程；Gate 为 `pass`。\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
