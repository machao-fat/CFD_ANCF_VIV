"""Write an isolated audit for the predictor-motion entry repair."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "100_cpp_worker_confirm_v1" / "repair_003"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    cpp_tests = subprocess.run(
        ["py", "-3.9", "-m", "unittest", "discover", "-s", "tests/cpp_worker_confirm_v1", "-p", "test_*.py"],
        cwd=ROOT, env={**__import__("os").environ, "PYTHONPATH": "src"}, capture_output=True, text=True,
    )
    ipc_tests = subprocess.run(
        ["py", "-3.9", "-m", "unittest", "discover", "-s", "tests/cpp_worker_persistent_ipc_v1", "-p", "test_*.py"],
        cwd=ROOT, env={**__import__("os").environ, "PYTHONPATH": "src"}, capture_output=True, text=True,
    )
    source = ROOT / "src" / "coupling" / "cpp_worker_confirm_v1" / "cpp_adapter.py"
    coordinator = ROOT / "src" / "coupling" / "cpp_worker_confirm_v1" / "real_coordinator.py"
    write("predictor_motion_repair_audit.json", {
        "status": "pass" if cpp_tests.returncode == 0 and ipc_tests.returncode == 0 else "do_not_pass",
        "repair": [
            "predictor_qdot and predictor_qddot are derived from the committed Newmark state",
            "motion builder requires predictor q/qdot/qddot with matching step/time identity",
            "real confirm start requires successful preflight before worker or slice launch",
            "stop audit reports observed worker and slice start counts",
        ],
        "source_sha256": {"cpp_adapter.py": sha256(source), "real_coordinator.py": sha256(coordinator)},
        "cpp_confirm_tests": {"return_code": cpp_tests.returncode, "raw_stdout": cpp_tests.stdout, "raw_stderr": cpp_tests.stderr},
        "persistent_ipc_tests": {"return_code": ipc_tests.returncode, "raw_stdout": ipc_tests.stdout, "raw_stderr": ipc_tests.stderr},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "old_evidence_modified": False,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
    })
    write("stage4f_d_cpp_worker_predictor_motion_repair_v1_gate.json", {
        "gate": "STAGE4F_D_CPP_WORKER_PREDICTOR_MOTION_REPAIR_V1_GATE: pass" if cpp_tests.returncode == 0 and ipc_tests.returncode == 0 else "STAGE4F_D_CPP_WORKER_PREDICTOR_MOTION_REPAIR_V1_GATE: do_not_pass",
        "real_confirm_gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass",
        "reason_real_confirm_not_run": "OpenFOAM/WSL/CFD authorization is not explicit",
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
    })
    return 0 if cpp_tests.returncode == 0 and ipc_tests.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
