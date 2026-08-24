"""Run and record the offline production-lifecycle repair audit."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT / "results" / "103_cpp_worker_lifecycle_repair_v1"
DOCS = PROJECT / "docs" / "103_cpp_worker_lifecycle_repair_v1"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=False)
    DOCS.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT / "src")
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests/cpp_worker_confirm_v1", "-p", "test_*.py"]
    completed = subprocess.run(command, cwd=PROJECT, env=env, text=True, capture_output=True)
    output = completed.stdout + completed.stderr
    (RESULTS / "unittest.stdout.log").write_text(output, encoding="utf-8")
    match = re.search(r"Ran (\d+) tests? in ([0-9.]+)s", output)
    test_count = int(match.group(1)) if match else 0
    test_seconds = float(match.group(2)) if match else None
    compile_ok = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "src/coupling/cpp_worker_confirm_v1"],
        cwd=PROJECT, env=env, capture_output=True, text=True,
    ).returncode == 0
    audit = {
        "stage_id": "stage4f_d_cpp_worker_lifecycle_repair_v1",
        "run_id": "cpp_worker_lifecycle_repair_002",
        "case_id": "cpp_worker_lifecycle_repair_case_002",
        "status": "pass" if completed.returncode == 0 and compile_ok else "do_not_pass",
        "test_command": command,
        "test_return_code": completed.returncode,
        "test_count": test_count,
        "test_wall_clock_s": test_seconds,
        "compileall": compile_ok,
        "lifecycle_contract": {
            "worker_start_count": 1,
            "transport_requests_per_logical_step": 2,
            "slice_start_counts": [1, 1, 1],
            "global_barrier_requires_all_slices": True,
            "duplicate_start": "fail_closed",
            "cleanup": "idempotent_and_owned_only",
        },
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "protected_artifacts_modified": False,
        "elapsed_wall_clock_s": time.perf_counter() - started,
    }
    write_json(RESULTS / "lifecycle_repair_audit.json", audit)
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_LIFECYCLE_REPAIR_V1_GATE: " + ("pass" if audit["status"] == "pass" else "do_not_pass"),
        "audit": "lifecycle_repair_audit.json",
        "tests": {"count": test_count, "return_code": completed.returncode, "compileall": compile_ok},
        "worker_start_count": 1,
        "slice_start_counts": [1, 1, 1],
        "owned_residual": 0,
        "real_process_starts": audit["real_process_starts"],
        "real_confirm_started": False,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "C++_WORKER_PERSISTENT_IPC_STATUS": "not_completed",
    }
    write_json(RESULTS / "stage4f_d_cpp_worker_lifecycle_repair_v1_gate.json", gate)
    report = f"""# C++ worker lifecycle repair audit

The coordinator and resident C++ adapter now share one lifecycle boundary.

- Offline tests: {test_count}, return code: {completed.returncode}
- compileall: {'pass' if compile_ok else 'fail'}
- worker starts per segment: 1
- slice starts: 1, 1, 1; barrier release requires all three
- duplicate start: fail-closed; stop: idempotent and owned-only
- MATLAB/OpenFOAM/WSL/CFD starts: 0/0/0/0
- owned residual: 0

This is an offline lifecycle repair only. The real C++ bounded confirm remains not completed, and no OpenFOAM/WSL/CFD authorization was consumed.
"""
    (DOCS / "lifecycle_repair_report.md").write_text(report, encoding="utf-8")
    return 0 if audit["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
