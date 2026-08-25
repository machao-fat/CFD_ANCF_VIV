from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "results" / "183_cpp_worker_comprehensive_audit_repair_v1" / "git_manifest.json"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    commit = git("rev-parse", "HEAD")
    parent = git("rev-parse", "HEAD^")
    names = [name for name in git("show", "--format=", "--name-only", commit).splitlines() if name]
    evidence = sorted(
        path for path in (ROOT / "results" / "183_cpp_worker_comprehensive_audit_repair_v1").iterdir()
        if path.is_file() and path.name != "git_manifest.json"
    )
    value = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "branch": git("branch", "--show-current"),
        "remote": git("remote", "get-url", "origin"),
        "parent_commit": parent,
        "new_commit": commit,
        "tag_to_create": "cfd-ancf-viv-cpp-worker-audit-repair-v1-stage183",
        "changed_files": names,
        "evidence_sha256": {path.name: sha256(path) for path in evidence},
        "gate": "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass",
        "numerical_status": "C++_ANCF_NUMERICAL_CORE_STATUS=not_completed",
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
    temporary.replace(TARGET)


if __name__ == "__main__":
    main()
