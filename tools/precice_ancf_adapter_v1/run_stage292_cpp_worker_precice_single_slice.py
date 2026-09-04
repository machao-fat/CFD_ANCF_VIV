"""Build a Linux C++ ANCF worker in WSL and run one fresh single-slice test."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "precice_ancf_adapter_v1"))
import run_stage290_cpp_worker_single_slice as base  # noqa: E402
RUNTIME = ROOT / "runtime" / "292_cpp_worker_precice_single_slice_040s_linux_v1"
BUILD_RUNTIME = ROOT / "runtime" / "292_cpp_worker_linux_build_v1"
WORKER = BUILD_RUNTIME / "cfd_ancf_ancf_kernel_worker"
RUN_ID = "stage292_cpp_worker_precice_single_slice_040s_linux_run_v1"
CASE_ID = "stage292_cpp_worker_precice_single_slice_040s_linux_case_v1"


def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def build_worker() -> dict[str, object]:
    if BUILD_RUNTIME.exists():
        raise RuntimeError(f"refusing to reuse existing build runtime: {BUILD_RUNTIME}")
    WORKER.parent.mkdir(parents=True, exist_ok=True)
    source = ROOT / "src" / "coupling" / "cpp_worker_persistent_ipc_v1"
    output = wsl(WORKER)
    src = wsl(source)
    command = (
        "set -e; "
        f"g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror "
        f"'{src}/ancf_kernel.cpp' '{src}/ancf_worker_main.cpp' "
        f"-I'{src}' -o '{output}'; "
        f"test -x '{output}'"
    )
    run = subprocess.run(["wsl.exe", "bash", "-lc", command], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    (BUILD_RUNTIME / "build.stdout.log").write_text(run.stdout, encoding="utf-8")
    (BUILD_RUNTIME / "build.stderr.log").write_text(run.stderr, encoding="utf-8")
    if run.returncode != 0 or not WORKER.is_file():
        raise RuntimeError(f"Linux worker build failed: return_code={run.returncode}")
    return {"return_code": run.returncode, "command": command, "path": str(WORKER),
            "sha256": hashlib.sha256(WORKER.read_bytes()).hexdigest(),
            "size_bytes": WORKER.stat().st_size}


def main() -> int:
    base.RUNTIME = RUNTIME
    base.CASE = RUNTIME / "case"
    base.LOGS = RUNTIME / "logs"
    base.OUT = ROOT / "results" / "292_cpp_worker_precice_single_slice_040s_linux_v1"
    base.WORKER = WORKER
    base.RUN_ID = RUN_ID
    base.CASE_ID = CASE_ID
    build = build_worker()
    result = base.main()
    out = ROOT / "results" / "292_cpp_worker_precice_single_slice_040s_linux_v1"
    gate_path = out / "stage4f_d_cpp_worker_precice_single_slice_040s_v1_gate.json"
    target_gate = out / "stage4f_d_cpp_worker_precice_single_slice_040s_linux_v1_gate.json"
    if gate_path.is_file():
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["gate_id"] = "STAGE4F_D_CPP_WORKER_PRECICE_SINGLE_SLICE_040S_LINUX_V1_GATE"
        gate["stage_id"] = "stage4f_d_cpp_worker_precice_single_slice_040s_linux_v1"
        gate["run_id"] = RUN_ID
        gate["case_id"] = CASE_ID
        gate["scope_contract"]["worker_platform"] = "WSL Linux ELF built from current source"
        gate["source_hashes"]["worker"] = build["sha256"]
        gate["real_process_counts"]["wsl"] = 2
        gate["real_process_counts"]["cpp_worker"] = 1
        gate["build"] = build
        target_gate.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
