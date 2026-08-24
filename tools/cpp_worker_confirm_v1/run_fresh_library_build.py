"""Execute a fresh OpenFOAM library build only after explicit authorization.

Default invocation is a dry-run audit.  The ``--execute`` path is the only
place this module can call WSL, and it requires the exact project authorization
token plus an independent fresh runtime prepared by
``prepare_fresh_library_build.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from coupling.cpp_worker_confirm_v1.contracts import REAL_AUTHORIZATION_TOKEN, ContractError
from coupling.cpp_worker_confirm_v1.library_build_guard import (
    LibraryBuildError, require_build_authorization, validate_build_output,
)


PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_004"
DEFAULT_RESULTS = PROJECT / "results/110_cpp_worker_library_build_v1"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--distro", default="Ubuntu-22.04")
    parser.add_argument("--openfoam-bashrc", default="/opt/openfoam10/etc/bashrc")
    parser.add_argument("--execute", action="store_true", help="required to launch WSL; omitted means dry-run")
    parser.add_argument("--authorization")
    args = parser.parse_args(argv)
    runtime, results = args.runtime.resolve(), args.results.resolve()
    output = runtime / "lib" / "libancfFileMotion.so"
    wsl_runtime = "/mnt/" + str(runtime.drive)[0].lower() + "/" + str(runtime.relative_to(runtime.anchor)).replace(chr(92), chr(47))
    wsl_output = wsl_runtime + "/lib/libancfFileMotion.so"
    command = ["wsl.exe", "-d", args.distro, "bash", "-lc",
               f"source {args.openfoam_bashrc} && cd {wsl_runtime}/source/ancfFileMotion && wmake libso && mkdir -p {wsl_runtime}/lib && cp /home/machao/OpenFOAM/machao-10/platforms/linux64GccDPInt32Opt/lib/libancfFileMotion.so {wsl_output}"]
    audit = {
        "stage_id": "stage4f_d_cpp_worker_library_build_v1",
        "run_id": "cpp_worker_library_build_001",
        "case_id": "cpp_worker_library_build_case_001",
        "runtime": str(runtime), "results": str(results), "output": str(output),
        "command": command, "execute_requested": bool(args.execute),
        "authorization_consumed": False,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
    }
    if not args.execute:
        audit["status"] = "prepared_only"
        audit["reason"] = "--execute was not provided; no WSL/OpenFOAM/CFD process may start"
        _write(results / "fresh_library_build_execution_audit.json", audit)
        print(json.dumps(audit, ensure_ascii=True, indent=2))
        return 0
    try:
        require_build_authorization(execute=True, authorization=args.authorization)
    except ContractError as exc:
        audit.update({"status": "do_not_pass", "failure_classification": "missing_explicit_authorization",
                      "error": str(exc)})
        _write(results / "fresh_library_build_execution_audit.json", audit)
        print(json.dumps(audit, ensure_ascii=True, indent=2))
        return 1
    if not runtime.is_dir() or not (runtime / "source" / "ancfFileMotion").is_dir():
        raise LibraryBuildError("prepared fresh source runtime is missing")
    if output.exists():
        raise LibraryBuildError("fresh runtime already contains a library; no overwrite or retry")
    started_ns = time.time_ns()
    completed = subprocess.run(command, cwd=runtime, capture_output=True, text=True)
    audit.update({
        "status": "built" if completed.returncode == 0 else "do_not_pass",
        "authorization_consumed": True, "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 1, "CFD": 0},
        "pid": None, "parent_pid": os.getpid(), "start_time_ns": started_ns, "end_time_ns": time.time_ns(),
        "return_code": completed.returncode,
    })
    (results / "fresh_library_build.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (results / "fresh_library_build.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode == 0:
        audit["library"] = validate_build_output(runtime=runtime, output=output)
    else:
        audit["failure_classification"] = "wsl_or_openfoam_build_nonzero"
    _write(results / "fresh_library_build_execution_audit.json", audit)
    print(json.dumps(audit, ensure_ascii=True, indent=2))
    return 0 if audit["status"] == "built" else 1


if __name__ == "__main__":
    raise SystemExit(main())
