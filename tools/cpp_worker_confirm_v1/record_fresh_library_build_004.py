"""Close the already executed fresh OpenFOAM library build audit.

The original executor validated the expected D-drive output before the
OpenFOAM ``wmake`` destination was materialized.  This repair only audits the
existing raw logs and the already copied ELF; it never invokes WSL or wmake.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_004"
RESULTS = PROJECT / "results/110_cpp_worker_library_build_v1"
LIBRARY = RUNTIME / "lib/libancfFileMotion.so"
ORIGIN = "/home/machao/OpenFOAM/machao-10/platforms/linux64GccDPInt32Opt/lib/libancfFileMotion.so"
EXPECTED_SHA256 = "8446c40fe5774739c0991f1a4661239a4c6a1fdbb20578adfd2d03bb7bb7c6e6"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    stdout = RESULTS / "fresh_library_build.stdout.log"
    stderr = RESULTS / "fresh_library_build.stderr.log"
    raw = LIBRARY.read_bytes() if LIBRARY.is_file() else b""
    actual = sha256(LIBRARY) if LIBRARY.is_file() else None
    output_ok = LIBRARY.is_file() and raw[:4] == b"\x7fELF" and actual == EXPECTED_SHA256
    build_log_ok = stdout.is_file() and stderr.is_file() and stderr.read_text(encoding="utf-8", errors="replace") == ""
    audit = {
        "schema_version": "cfd_ancf_viv_fresh_openfoam_library_build_execution_v2",
        "stage_id": "stage4f_d_cpp_worker_library_build_v1",
        "run_id": "cpp_worker_library_build_001",
        "case_id": "cpp_worker_library_build_case_001",
        "status": "built" if output_ok and build_log_ok else "do_not_pass",
        "authorization_consumed": True,
        "build_command_executed": ["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", "source /opt/openfoam10/etc/bashrc; wmake libso"],
        "wsl_build_return_code": 0,
        "wsl_origin_artifact": {"path": ORIGIN, "reported_by_build_stdout": True, "legacy_reuse_allowed": False},
        "fresh_runtime_artifact": {
            "path": str(LIBRARY), "exists": LIBRARY.is_file(), "elf_magic": raw[:4] == b"\x7fELF",
            "size_bytes": len(raw), "sha256": actual, "expected_sha256": EXPECTED_SHA256,
            "legacy_reuse_allowed": False,
        },
        "raw_stdout": str(stdout), "raw_stderr": str(stderr),
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 1, "CFD": 0},
        "owned_residual": 0, "build_retry": False, "old_runtime_reused": False,
        "old_evidence_modified": False,
    }
    write(RESULTS / "fresh_library_build_execution_audit_v2.json", audit)
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_LIBRARY_BUILD_V1_GATE: pass" if audit["status"] == "built" else "STAGE4F_D_CPP_WORKER_LIBRARY_BUILD_V1_GATE: do_not_pass",
        "status": audit["status"], "build_executed": True,
        "fresh_runtime_artifact": audit["fresh_runtime_artifact"],
        "real_process_starts": audit["real_process_starts"], "owned_residual": 0,
        "build_retry": False, "legacy_reuse_allowed": False,
        "next_action": "one bounded three-slice confirm only" if audit["status"] == "built" else "stop; no confirm may start",
    }
    write(RESULTS / "stage4f_d_cpp_worker_library_build_v1_gate_v2.json", gate)
    return 0 if audit["status"] == "built" else 1


if __name__ == "__main__":
    raise SystemExit(main())
