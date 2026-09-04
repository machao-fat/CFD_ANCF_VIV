"""Read-only validation of the fresh Stage 228 build artifacts."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT / "results/228_cpp_worker_to70s_build_retry_v7"
RUNTIME = PROJECT / "runtime/cpp_worker_to70s_build_retry_v7"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _process_audit() -> dict[str, object]:
    names = {"matlab.exe", "simpleFoam", "pimpleFoam", "cfd_ancf_ancf_kernel_worker"}
    command = "Get-CimInstance Win32_Process | Select-Object Name,ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
    try:
        raw = subprocess.check_output(["powershell", "-NoProfile", "-Command", command],
                                      text=True, encoding="utf-8", errors="replace")
        parsed = json.loads(raw) if raw.strip() else []
        if isinstance(parsed, dict):
            parsed = [parsed]
        found = [row for row in parsed if row.get("Name") in names]
        return {"status": "pass", "target_processes": found}
    except Exception as exc:
        return {"status": "do_not_pass", "target_processes": [], "error": str(exc)}


def main() -> int:
    audit_path = RESULTS / "build_execution_audit.json"
    build = json.loads(audit_path.read_text(encoding="utf-8"))
    library = Path(str(build["library"]["path"]))
    worker = Path(str(build["worker"]["path"]))
    rows = []
    for label, path, expected in (("library", library, build["library"]["sha256"]),
                                  ("worker", worker, build["worker"]["sha256"])):
        exists = path.is_file()
        actual = _sha(path) if exists else None
        raw = path.read_bytes() if exists else b""
        rows.append({"name": label, "path": str(path), "exists": exists,
                     "size_bytes": len(raw) if exists else None,
                     "sha256": actual, "expected_sha256": expected,
                     "hash_ok": exists and actual == expected,
                     "elf_magic": raw[:4] == b"\x7fELF"})
    process = _process_audit()
    checks = {
        "build_status": build.get("status") == "built",
        "all_build_steps_zero": all(row.get("return_code") == 0 for row in build.get("build_steps", [])),
        "artifacts": all(row["exists"] and row["hash_ok"] and row["elf_magic"] for row in rows),
        "runtime_is_fresh": str(RUNTIME) == str(Path(build.get("runtime", "")).resolve()),
        "target_processes_absent": process["status"] == "pass" and not process["target_processes"],
    }
    passed = all(checks.values())
    result = {
        "gate": f"STAGE4F_D_CPP_WORKER_TO70S_ARTIFACT_PREFLIGHT_V1_GATE: {'pass' if passed else 'do_not_pass'}",
        "status": "pass" if passed else "do_not_pass", "checks": checks,
        "artifacts": rows, "process_audit": process,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0, "old_runtime_reused": False,
        "ready_for_real_segment": False,
        "reason": "artifact preflight does not authorize or start a CFD segment",
    }
    (RESULTS / "artifact_preflight.json").write_text(json.dumps(result, ensure_ascii=True,
                                                                 sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
