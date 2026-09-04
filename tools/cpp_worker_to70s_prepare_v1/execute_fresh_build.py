"""Execute the explicitly authorized Stage 221 fresh builds once."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_confirm_v1.contracts import REAL_AUTHORIZATION_TOKEN  # noqa: E402
from coupling.cpp_worker_confirm_v1.library_build_guard import validate_build_output  # noqa: E402

RUNTIME = PROJECT / "runtime/cpp_worker_to70s_build_prepare_v1"
RESULTS = PROJECT / "results/221_cpp_worker_to70s_build_prepare_v1"
DISTRO = "Ubuntu-22.04"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wsl_path(path: Path) -> str:
    relative = path.resolve().relative_to(path.anchor)
    return "/mnt/" + path.drive[0].lower() + "/" + str(relative).replace("\\", "/")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True,
                               indent=2) + "\n", encoding="utf-8")


def _run(command: list[str], *, log_stem: str) -> dict[str, object]:
    started_ns = time.time_ns()
    process = subprocess.Popen(command, cwd=str(RUNTIME), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               errors="replace")
    stdout, stderr = process.communicate()
    ended_ns = time.time_ns()
    (RESULTS / f"{log_stem}.stdout.log").write_text(stdout, encoding="utf-8")
    (RESULTS / f"{log_stem}.stderr.log").write_text(stderr, encoding="utf-8")
    return {"pid": int(process.pid), "parent_pid": os.getpid(),
            "command_line": command, "start_time_ns": started_ns,
            "end_time_ns": ended_ns, "return_code": process.returncode,
            "owned": True, "cleanup_result": "closed",
            "stdout_log": str(RESULTS / f"{log_stem}.stdout.log"),
            "stderr_log": str(RESULTS / f"{log_stem}.stderr.log")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorization")
    args = parser.parse_args(argv)
    RESULTS.mkdir(parents=True, exist_ok=True)
    audit: dict[str, object] = {
        "stage_id": "stage4f_d_cpp_worker_to70s_build_prepare_v1",
        "run_id": "cpp_worker_to70s_build_prepare_001",
        "case_id": "cpp_worker_to70s_build_prepare_case_001",
        "runtime": str(RUNTIME), "results": str(RESULTS),
        "execute_requested": bool(args.execute), "authorization_consumed": False,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0, "build_steps": [],
    }
    if not args.execute:
        audit.update({"status": "prepared_only", "reason": "--execute is required"})
        _write(RESULTS / "fresh_build_execution_audit.json", audit)
        return 0
    if args.authorization != REAL_AUTHORIZATION_TOKEN:
        audit.update({"status": "do_not_pass", "reason": "authorization mismatch"})
        _write(RESULTS / "fresh_build_execution_audit.json", audit)
        return 1
    if not RUNTIME.is_dir() or not (RUNTIME / "source" / "ancfFileMotion").is_dir():
        audit.update({"status": "do_not_pass", "reason": "fresh prepared runtime is missing"})
        _write(RESULTS / "fresh_build_execution_audit.json", audit)
        return 1
    output = RUNTIME / "lib" / "libancfFileMotion.so"
    if output.exists():
        audit.update({"status": "do_not_pass", "reason": "fresh output already exists; refusing overwrite"})
        _write(RESULTS / "fresh_build_execution_audit.json", audit)
        return 1
    runtime_wsl = _wsl_path(RUNTIME)
    source_wsl = _wsl_path(RUNTIME / "source" / "ancfFileMotion")
    library_command = ["wsl.exe", "-d", DISTRO, "bash", "-lc",
                       f"set -e; source /opt/openfoam10/etc/bashrc; cd '{source_wsl}'; wmake libso; mkdir -p '{runtime_wsl}/lib'; cp /home/machao/OpenFOAM/machao-10/platforms/linux64GccDPInt32Opt/lib/libancfFileMotion.so '{runtime_wsl}/lib/libancfFileMotion.so'"]
    library_audit = _run(library_command, log_stem="fresh_library_build")
    audit["build_steps"].append({"name": "ancfFileMotion", **library_audit})
    audit["real_process_starts"] = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 1, "CFD": 0}
    if int(library_audit["return_code"]) != 0:
        audit.update({"status": "do_not_pass", "failure_classification": "library_build_nonzero"})
        _write(RESULTS / "fresh_build_execution_audit.json", audit)
        return 1
    try:
        library = validate_build_output(runtime=RUNTIME, output=output)
    except Exception as exc:
        audit.update({"status": "do_not_pass", "failure_classification": "library_output_invalid",
                      "error": str(exc)})
        _write(RESULTS / "fresh_build_execution_audit.json", audit)
        return 1
    audit["library"] = library
    worker_build = RUNTIME / "cpp_worker_build"
    if worker_build.exists() and any(worker_build.iterdir()):
        audit.update({"status": "do_not_pass", "failure_classification": "worker_build_dir_not_fresh"})
        _write(RESULTS / "fresh_build_execution_audit.json", audit)
        return 1
    source_cpp = _wsl_path(PROJECT / "src" / "coupling" / "cpp_worker_persistent_ipc_v1")
    build_wsl = _wsl_path(worker_build)
    worker_command = ["wsl.exe", "-d", DISTRO, "bash", "-lc",
                      f"set -e; cmake -S '{source_cpp}' -B '{build_wsl}' -DCMAKE_BUILD_TYPE=Release; cmake --build '{build_wsl}' --target cfd_ancf_ancf_kernel_worker --config Release -j2"]
    worker_audit = _run(worker_command, log_stem="cpp_worker_build")
    audit["build_steps"].append({"name": "cpp_worker", **worker_audit})
    audit["real_process_starts"] = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 2, "CFD": 0}
    if int(worker_audit["return_code"]) != 0:
        audit.update({"status": "do_not_pass", "failure_classification": "cpp_worker_build_nonzero"})
        _write(RESULTS / "fresh_build_execution_audit.json", audit)
        return 1
    candidates = [path for path in worker_build.rglob("cfd_ancf_ancf_kernel_worker*")
                  if path.is_file() and path.name not in {"CMakeFiles"}]
    candidates = [path for path in candidates if path.suffix in {"", ".exe"}]
    if len(candidates) != 1:
        audit.update({"status": "do_not_pass", "failure_classification": "worker_output_ambiguous",
                      "worker_candidates": [str(path) for path in candidates]})
        _write(RESULTS / "fresh_build_execution_audit.json", audit)
        return 1
    worker = candidates[0]
    raw = worker.read_bytes()
    audit["worker"] = {"path": str(worker), "size_bytes": len(raw), "sha256": _sha(worker),
                        "elf_magic": raw[:4] == b"\x7fELF", "legacy_reuse_allowed": False}
    audit["authorization_consumed"] = True
    audit["status"] = "built"
    _write(RESULTS / "fresh_build_execution_audit.json", audit)
    _write(RESULTS / "stage4f_d_cpp_worker_to70s_build_prepare_v1_gate.json", {
        "gate": "STAGE4F_D_CPP_WORKER_TO70S_BUILD_PREPARE_V1_GATE: pass",
        "status": "pass", "build_performed": True, "library": audit["library"],
        "worker": audit["worker"], "build_steps": audit["build_steps"],
        "real_process_starts": audit["real_process_starts"], "owned_residual": 0,
        "old_runtime_reused": False, "stage75_started": False, "e5c_started": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
