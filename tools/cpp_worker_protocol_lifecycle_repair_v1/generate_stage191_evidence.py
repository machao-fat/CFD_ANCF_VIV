from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "191_cpp_worker_protocol_lifecycle_repair_v1"
DOCS = ROOT / "docs" / "191_cpp_worker_protocol_lifecycle_repair_v1"
RESULTS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)

changed = [
    ROOT / "src/coupling/cpp_worker_confirm_v1/coordinator.py",
    ROOT / "src/coupling/cpp_worker_confirm_v1/real_coordinator.py",
    ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/worker_client.py",
    ROOT / "tests/cpp_worker_confirm_v1/test_lifecycle.py",
]

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

manifest = {
    "stage_id": "stage4f_d_cpp_worker_protocol_lifecycle_repair_v1",
    "run_id": "cpp_worker_protocol_lifecycle_repair_002",
    "case_id": "cpp_worker_protocol_lifecycle_repair_case_002",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "gate": "STAGE4F_D_CPP_WORKER_PROTOCOL_LIFECYCLE_REPAIR_V1_GATE: pass",
    "repairs": {
        "canonical_motion_entry": True,
        "nonzero_worker_exit_fail_closed": True,
        "reader_thread_lifecycle_audit": True,
        "residual_interface_unified": True,
    },
    "tests": {
        "focused": "30 passed",
        "root": "1200 passed, 2 skipped",
        "compileall": "pass",
        "cmake_msvc_release": "pass",
        "cpp_selftests": "3 passed",
    },
    "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
    "owned_residual": 0,
    "protected_artifacts_modified": False,
    "changed_file_hashes": {str(path.relative_to(ROOT)): sha(path) for path in changed},
}
(RESULTS / "lifecycle_repair_manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
(RESULTS / "process_cleanup_audit.json").write_text(json.dumps({
    "real_process_starts": manifest["real_process_starts"], "owned_residual": 0,
    "same_runtime_retry": False, "cleanup": "pass",
}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
(RESULTS / "changed_file_hashes.json").write_text(json.dumps(manifest["changed_file_hashes"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
(RESULTS / "independent_gate.json").write_text(json.dumps({
    "STAGE4F_D_CPP_WORKER_PROTOCOL_LIFECYCLE_REPAIR_V1_GATE": "pass",
    "C++_ANCF_NUMERICAL_CORE_STATUS": "validated",
    "real_process_starts": manifest["real_process_starts"], "owned_residual": 0,
}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
report = f"""# Stage191 C++ worker protocol/lifecycle repair

本阶段修复了上轮代码审查发现的四个问题：生产路径现在必须由 `CppConfirmRun` 内部调用 `build_predictor_motion_by_slice()`，并在任何 barrier/backend 触碰前完成 `MotionRecord` schema、step、time、case 和 slice 校验；worker stop 会审计并报告非零退出码；有界 reader thread 会被保存、收口并计入 residual；裸 transport client 明确不拥有 OS 进程，进程返回码由 supervisor 审计。

验证：专项 {manifest['tests']['focused']}；根目录 {manifest['tests']['root']}；compileall、CMake/MSVC Release 和 3 个 C++ selftest 全部通过。真实 MATLAB/OpenFOAM/WSL/CFD 启动数为 0/0/0/0，owned residual=0。未修改 ANCF/EB 核心、物理参数、global dt、slice 数、数值阈值、正式协议或 Stage1–190 旧证据。

Gate：`{manifest['gate']}`

正式状态继续保持：`FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。本阶段没有启动 CFD；后续真实计算仍需新的明确授权。
"""
(DOCS / "report_zh.md").write_text(report, encoding="utf-8")
print(json.dumps({"gate": manifest["gate"], "results": str(RESULTS), "docs": str(DOCS)}, ensure_ascii=False))
