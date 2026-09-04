"""Read-only artifact preflight for the fresh Stage 232 build."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT / "results/232_cpp_worker_to70s_build_retry_v11"
RUNTIME = PROJECT / "runtime/cpp_worker_to70s_build_retry_v11"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _targets_absent() -> dict[str, object]:
    names = {"matlab.exe", "simpleFoam", "pimpleFoam", "cfd_ancf_ancf_kernel_worker.exe"}
    command = "Get-CimInstance Win32_Process | Select-Object Name,ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
    try:
        raw = subprocess.check_output(["powershell", "-NoProfile", "-Command", command],
                                      text=True, encoding="utf-8", errors="replace")
        parsed = json.loads(raw) if raw.strip() else []
        if isinstance(parsed, dict):
            parsed = [parsed]
        return {"status": "pass", "target_processes": [row for row in parsed if row.get("Name") in names]}
    except Exception as exc:
        return {"status": "do_not_pass", "target_processes": [], "error": str(exc)}


def _library_dependencies(path: Path) -> dict[str, object]:
    wsl_path = "/mnt/" + path.drive[0].lower() + "/" + str(path.resolve().relative_to(path.anchor)).replace("\\", "/")
    command = ("source /opt/openfoam10/etc/bashrc; "
               f"ldd -r '{wsl_path}' 2>&1 | grep -E 'not found|undefined symbol' || true")
    try:
        raw = subprocess.check_output(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command],
                                      text=True, encoding="utf-8", errors="replace")
        return {"status": "pass" if not raw.strip() else "do_not_pass", "unresolved": raw.splitlines()}
    except Exception as exc:
        return {"status": "do_not_pass", "unresolved": [], "error": str(exc)}


def main() -> int:
    build = json.loads((RESULTS / "build_execution_audit.json").read_text(encoding="utf-8"))
    library = Path(str(build["library"]["path"]))
    worker = Path(str(build["worker"]["path"]))
    library_raw = library.read_bytes() if library.is_file() else b""
    worker_raw = worker.read_bytes() if worker.is_file() else b""
    rows = {
        "library": {"path": str(library), "exists": library.is_file(),
                    "size_bytes": len(library_raw) if library.is_file() else None,
                    "sha256": _sha(library) if library.is_file() else None,
                    "expected_sha256": build["library"]["sha256"],
                    "hash_ok": library.is_file() and _sha(library) == build["library"]["sha256"],
                    "elf_magic": library_raw[:4] == b"\x7fELF"},
        "worker": {"path": str(worker), "exists": worker.is_file(),
                   "size_bytes": len(worker_raw) if worker.is_file() else None,
                   "sha256": _sha(worker) if worker.is_file() else None,
                   "expected_sha256": build["worker"]["sha256"],
                   "hash_ok": worker.is_file() and _sha(worker) == build["worker"]["sha256"],
                   "pe_magic": worker_raw[:2] == b"MZ", "name_allowed": worker.name.lower() == "cfd_ancf_ancf_kernel_worker.exe"},
    }
    dependencies = _library_dependencies(library)
    processes = _targets_absent()
    checks = {
        "build_status": build.get("status") == "built",
        "build_steps_zero": all(row.get("return_code") == 0 for row in build.get("build_steps", [])),
        "library_valid": rows["library"]["exists"] and rows["library"]["hash_ok"] and rows["library"]["elf_magic"],
        "windows_worker_valid": rows["worker"]["exists"] and rows["worker"]["hash_ok"] and rows["worker"]["pe_magic"] and rows["worker"]["name_allowed"],
        "library_dependencies_resolved": dependencies["status"] == "pass",
        "target_processes_absent": processes["status"] == "pass" and not processes["target_processes"],
        "fresh_runtime": str(RUNTIME) == str(Path(build["runtime"]).resolve()),
    }
    passed = all(checks.values())
    result = {
        "gate": f"STAGE4F_D_CPP_WORKER_TO70S_ARTIFACT_PREFLIGHT_V2_GATE: {'pass' if passed else 'do_not_pass'}",
        "status": "pass" if passed else "do_not_pass", "checks": checks,
        "artifacts": rows, "library_dependencies": dependencies, "process_audit": processes,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "probe_process_starts": {"WSL": 1, "CFD": 0, "OpenFOAM": 0, "MATLAB": 0},
        "owned_residual": 0, "old_runtime_reused": False,
        "ready_for_real_segment": False,
        "reason": "artifact preflight does not authorize or start a CFD segment; a fresh 0 s contract and case staging remain required",
    }
    (RESULTS / "artifact_preflight_v2.json").write_text(json.dumps(result, ensure_ascii=True,
                                                                    sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
