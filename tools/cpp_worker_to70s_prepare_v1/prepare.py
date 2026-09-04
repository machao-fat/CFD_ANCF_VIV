"""Prepare fresh worker/library build inputs without launching WSL."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_confirm_v1.library_build_guard import prepare_fresh_library_build  # noqa: E402

STAGE_ID = "stage4f_d_cpp_worker_to70s_build_prepare_v1"
RUN_ID = "cpp_worker_to70s_build_prepare_001"
CASE_ID = "cpp_worker_to70s_build_prepare_case_001"
RUNTIME = PROJECT / "runtime/cpp_worker_to70s_build_prepare_v1"
RESULTS = PROJECT / "results/221_cpp_worker_to70s_build_prepare_v1"
SOURCE = PROJECT / "src/openfoam/ancfFileMotion"
CPP_SOURCE = PROJECT / "src/coupling/cpp_worker_persistent_ipc_v1"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True,
                               indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("Stage 221 destination already exists; refusing reuse")
    plan = prepare_fresh_library_build(project_root=PROJECT, runtime=RUNTIME,
                                       results=RESULTS, source_tree=SOURCE)
    cpp_files = []
    for path in sorted(CPP_SOURCE.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".cpp", ".hpp", ".h", ".cxx", ".cmake"}:
            cpp_files.append({"path": str(path.relative_to(PROJECT)), "sha256": _sha(path),
                              "size_bytes": path.stat().st_size})
    evidence = {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "status": "pass", "prepared_only": True,
        "library_plan": plan,
        "cpp_worker_source": {"root": str(CPP_SOURCE), "file_count": len(cpp_files),
                               "files": cpp_files, "build_performed": False},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0, "old_runtime_reused": False,
        "next_authorization": "WSL/OpenFOAM build authorization is required before executing wmake or cmake",
    }
    _write(RESULTS / "build_prepare_audit.json", evidence)
    _write(RESULTS / "stage4f_d_cpp_worker_to70s_build_prepare_v1_gate.json", {
        "gate": "STAGE4F_D_CPP_WORKER_TO70S_BUILD_PREPARE_V1_GATE: pass",
        "status": "pass", "prepared_only": True,
        "real_process_starts": evidence["real_process_starts"],
        "owned_residual": 0, "old_runtime_reused": False,
        "library_source_file_count": plan["source_file_count"],
        "cpp_worker_source_file_count": len(cpp_files),
        "build_performed": False,
    })
    docs = PROJECT / "docs/221_cpp_worker_to70s_build_prepare_v1"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "report.md").write_text(
        "# Stage 221 fresh build preparation\n\n"
        "- Preparation Gate: `STAGE4F_D_CPP_WORKER_TO70S_BUILD_PREPARE_V1_GATE: pass`\n"
        "- Fresh OpenFOAM motion source was copied and hashed into a new runtime.\n"
        f"- C++ worker source files hashed: {len(cpp_files)}; no C++ build was executed.\n"
        "- No WSL, OpenFOAM, MATLAB, or CFD process was started.\n"
        "- The next action requiring explicit authorization is the fresh worker/library build, followed by a read-only artifact preflight.\n",
        encoding="utf-8")
    print(json.dumps({"gate": "STAGE4F_D_CPP_WORKER_TO70S_BUILD_PREPARE_V1_GATE: pass",
                      "runtime": str(RUNTIME), "results": str(RESULTS)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
