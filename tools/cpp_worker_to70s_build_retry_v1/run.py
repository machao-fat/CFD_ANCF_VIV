"""Prepare and execute one fresh Stage 222 worker/library build.

This is a build-only entry point.  It never starts a CFD case, OpenFOAM
solver, MATLAB, or WSL-backed simulation.  A failed command is terminal for
this runtime; there is no retry path.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))
from coupling.cpp_worker_confirm_v1.library_build_guard import (  # noqa: E402
    prepare_fresh_library_build, validate_build_output,
)

STAGE_ID = "stage4f_d_cpp_worker_to70s_build_retry_v11"
RUN_ID = "cpp_worker_to70s_build_retry_011"
CASE_ID = "cpp_worker_to70s_build_retry_case_011"
RUNTIME = PROJECT / "runtime/cpp_worker_to70s_build_retry_v11"
RESULTS = PROJECT / "results/232_cpp_worker_to70s_build_retry_v11"
DOCS = PROJECT / "docs/232_cpp_worker_to70s_build_retry_v11"
SOURCE = PROJECT / "src/openfoam/ancfFileMotion"
DISTRO = "Ubuntu-22.04"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wsl_path(path: Path) -> str:
    path = path.resolve()
    return "/mnt/" + path.drive[0].lower() + "/" + str(path.relative_to(path.anchor)).replace("\\", "/")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _run(command: list[str], stem: str) -> dict[str, object]:
    started_ns = time.time_ns()
    proc = subprocess.Popen(command, cwd=str(RUNTIME), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    stdout, stderr = proc.communicate()
    ended_ns = time.time_ns()
    out = RESULTS / f"{stem}.stdout.log"
    err = RESULTS / f"{stem}.stderr.log"
    out.write_text(stdout, encoding="utf-8")
    err.write_text(stderr, encoding="utf-8")
    return {"pid": int(proc.pid), "parent_pid": os.getpid(), "command_line": command,
            "start_time_ns": started_ns, "end_time_ns": ended_ns,
            "return_code": proc.returncode, "owned": True, "cleanup_result": "closed",
            "stdout_log": str(out), "stderr_log": str(err)}


def main() -> int:
    if RUNTIME.exists() or RESULTS.exists() or DOCS.exists():
        raise RuntimeError("Stage 222 destination already exists; refusing reuse")
    DOCS.mkdir(parents=True)
    audit: dict[str, object] = {"stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
                                "runtime": str(RUNTIME), "results": str(RESULTS),
                                "build_steps": [], "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
                                "owned_residual": 0, "old_runtime_reused": False}
    try:
        plan = prepare_fresh_library_build(project_root=PROJECT, runtime=RUNTIME,
                                           results=RESULTS, source_tree=SOURCE)
        audit["library_plan"] = plan
        RESULTS.mkdir(parents=True, exist_ok=True)
        make_dir = RUNTIME / "source" / "ancfFileMotion" / "Make"
        make_files = make_dir / "files"
        platform_files = make_dir / "linux64GccDPInt32Opt" / "files"
        make_files_before = _sha(make_files)
        make_override = (
            "SOURCE += ancfFileMotion.C\n\n"
            f"LIB = {_wsl_path(RUNTIME / 'lib' / 'libancfFileMotion')}\n")
        make_files.write_text(make_override, encoding="utf-8")
        platform_files.write_text(make_override, encoding="utf-8")
        audit["stage_local_make_files_override"] = {
            "path": str(make_files), "platform_path": str(platform_files),
            "before_sha256": make_files_before, "after_sha256": _sha(make_files),
            "platform_sha256": _sha(platform_files), "origin_source_modified": False,
        }
    except Exception as exc:
        audit.update({"status": "do_not_pass", "failure_classification": "fresh_prepare", "error": str(exc)})
        _write(RESULTS / "build_execution_audit.json", audit)
        return 1

    runtime_wsl = _wsl_path(RUNTIME)
    source_wsl = _wsl_path(RUNTIME / "source" / "ancfFileMotion")
    # Use FOAM_USER_LIBBIN produced by the selected OpenFOAM bashrc rather
    # than a stale user-specific path from a previous installation.
    library_cmd = ["wsl.exe", "-d", DISTRO, "bash", "-lc",
                   f"source /opt/openfoam10/etc/bashrc; set -exo pipefail; export FOAM_USER_LIBBIN='{runtime_wsl}/lib'; mkdir -p '{runtime_wsl}/lib'; cd '{source_wsl}'; wmake libso; test -f '{runtime_wsl}/lib/libancfFileMotion.so'"]
    library_audit = _run(library_cmd, "fresh_library_build")
    audit["build_steps"].append({"name": "ancfFileMotion", **library_audit})
    audit["real_process_starts"] = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 1, "CFD": 0}
    if library_audit["return_code"] != 0:
        audit.update({"status": "do_not_pass", "failure_classification": "library_build_nonzero"})
        _write(RESULTS / "build_execution_audit.json", audit)
        return 1
    try:
        audit["library"] = validate_build_output(runtime=RUNTIME, output=RUNTIME / "lib/libancfFileMotion.so")
    except Exception as exc:
        audit.update({"status": "do_not_pass", "failure_classification": "library_output_invalid", "error": str(exc)})
        _write(RESULTS / "build_execution_audit.json", audit)
        return 1

    worker_build = RUNTIME / "cpp_worker_build"
    source_cpp = PROJECT / "src" / "coupling" / "cpp_worker_persistent_ipc_v1"
    worker_build.mkdir(parents=True, exist_ok=False)
    worker_exe = worker_build / "cfd_ancf_ancf_kernel_worker.exe"
    vsdev = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat")
    if not vsdev.is_file():
        audit.update({"status": "do_not_pass", "failure_classification": "msvc_toolchain_missing"})
        _write(RESULTS / "build_execution_audit.json", audit)
        return 1
    worker_cmdline = (
        'call C:\\PROGRA~2\\MICROS~4\\2022\\BUILDT~1\\Common7\\Tools\\VsDevCmd.bat -arch=x64 && '
        f'cl /nologo /std:c++17 /O2 /EHsc /W4 /WX /I{source_cpp} '
        f'{source_cpp / "ancf_kernel.cpp"} {source_cpp / "ancf_worker_main.cpp"} '
        f'/link bcrypt.lib /OUT:{worker_exe}'
    )
    worker_cmd = ["cmd.exe", "/d", "/c", worker_cmdline]
    worker_audit = _run(worker_cmd, "cpp_worker_build")
    audit["build_steps"].append({"name": "cpp_worker", **worker_audit})
    audit["real_process_starts"] = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 2, "CFD": 0}
    if worker_audit["return_code"] != 0:
        audit.update({"status": "do_not_pass", "failure_classification": "cpp_worker_build_nonzero"})
        _write(RESULTS / "build_execution_audit.json", audit)
        return 1
    candidates = [p for p in worker_build.rglob("cfd_ancf_ancf_kernel_worker*")
                  if p.is_file() and p.suffix in {"", ".exe"}]
    if len(candidates) != 1:
        audit.update({"status": "do_not_pass", "failure_classification": "worker_output_ambiguous",
                      "worker_candidates": [str(p) for p in candidates]})
        _write(RESULTS / "build_execution_audit.json", audit)
        return 1
    worker = candidates[0]
    raw = worker.read_bytes()
    audit["worker"] = {"path": str(worker), "size_bytes": len(raw), "sha256": _sha(worker),
                        "elf_magic": raw[:4] == b"\x7fELF", "legacy_reuse_allowed": False}
    audit.update({"status": "built", "authorization_consumed": True})
    _write(RESULTS / "build_execution_audit.json", audit)
    _write(RESULTS / "stage4f_d_cpp_worker_to70s_build_retry_v1_gate.json", {
        "gate": "STAGE4F_D_CPP_WORKER_TO70S_BUILD_RETRY_V1_GATE: pass",
        "status": "pass", "library": audit["library"], "worker": audit["worker"],
        "build_steps": audit["build_steps"], "real_process_starts": audit["real_process_starts"],
        "owned_residual": 0, "old_runtime_reused": False, "stage75_started": False,
        "e5c_started": False,
    })
    (DOCS / "report.md").write_text(
        "# Stage 222 fresh worker/library build\n\n"
        "- This build used a new runtime after the terminal Stage 231 MSVC source quoting failure.\n"
        "- OpenFOAM motion library and C++ worker were built once each; no CFD case was started.\n"
        f"- Library: `{audit['library']['path']}` SHA-256 `{audit['library']['sha256']}`.\n"
        f"- Worker: `{audit['worker']['path']}` SHA-256 `{audit['worker']['sha256']}`.\n"
        "- A fresh artifact preflight is required before any real segment authorization.\n",
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
