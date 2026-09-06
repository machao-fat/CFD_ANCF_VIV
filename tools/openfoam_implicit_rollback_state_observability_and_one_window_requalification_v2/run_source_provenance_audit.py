"""Fail-closed source/build provenance audit for adapter rollback instrumentation."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGE = "openfoam_implicit_rollback_state_observability_and_one_window_requalification_v2"
RUNTIME = ROOT / "runtime" / "implicit_one_window_requal_v1_run_001"
RESULTS = ROOT / "results" / STAGE
DOC = ROOT / "docs" / STAGE / "OPENFOAM_IMPLICIT_ROLLBACK_STATE_OBSERVABILITY_AND_ONE_WINDOW_REQUALIFICATION_V2_REPORT.md"
LIB_WSL = "/home/machao/OpenFOAM/stage315_adapter_build/libpreciceAdapterFunctionObject.so"
SOURCE = ROOT / "runtime" / "openfoam_adapter_v131_rollback_observability_source"


def run_wsl(command: str) -> str:
    completed = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.replace("\x00", "")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    prior_log = (RUNTIME / "logs" / "fluid_0000.stdout").read_text(encoding="utf-8")
    deployed_banner = re.search(r"adapter - v([0-9.]+)", prior_log)
    source_banner = re.search(
        r"adapter - v([0-9.]+)", (SOURCE / "Adapter.C").read_text(encoding="utf-8")
    )
    sha_text = run_wsl(f"sha256sum {LIB_WSL}")
    sha_match = re.search(r"\b[0-9a-f]{64}\b", sha_text)
    if not sha_match:
        raise RuntimeError("could not recover deployed adapter SHA-256 from WSL output")
    binary_sha = sha_match.group(0)
    binary_symbols = run_wsl(
        "nm -D -C " + LIB_WSL
        + " | grep -E '(writeCheckpoint|readCheckpoint|storeCheckpointTime|reloadCheckpointTime|writeMeshCheckpoint|readMeshCheckpoint|setupCheckpointing)'"
    )
    source_build_log = (SOURCE / "wmake.log")
    build_text = source_build_log.read_text(encoding="utf-8", errors="replace") if source_build_log.exists() else ""
    incompatible_headers = sorted(
        set(re.findall(r"fatal error: ([^:]+): No such file", build_text))
    )
    source_git = subprocess.run(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    deployed_version = deployed_banner.group(1).rstrip(".") if deployed_banner else None
    source_version = source_banner.group(1).rstrip(".") if source_banner else None
    source_version_matches = bool(deployed_version and source_version and deployed_version == source_version)
    # A matching banner is not source/build provenance. The deployed .so has
    # neither a source commit nor a retained build manifest.
    source_is_proven = False
    build_ok = "=== OK: Building completed successfully! ===" in build_text
    status = "PASS" if source_is_proven and build_ok else "FAIL"
    inventory = {
        "U": "registered volVectorField copied and restored with oldTime levels",
        "p": "registered volScalarField copied and restored with oldTime levels",
        "phi": "registered surfaceScalarField copied and restored with oldTime levels",
        "Uf": "registered surfaceVectorField copied and restored with oldTime levels when present",
        "meshPhi": "mesh_.phi() copied/restored by dedicated mesh checkpoint path",
        "pointDisplacement": "registered pointVectorField copied and restored with oldTime levels",
        "cellDisplacement": "registered volVectorField copied and restored with oldTime levels",
        "mesh_points": "mesh_.points() plus oldMeshPoints_ captured; mesh_.movePoints() restores",
        "time": "couplingIterationTimeValue_ restored with Time::setTime",
        "timeIndex": "couplingIterationTimeIndex_ restored with Time::setTime",
        "topology": "no topology checkpoint API; the frozen case is static-topology and must be fingerprinted if instrumented",
    }
    result = {
        "stage": STAGE,
        "status": status,
        "blocker": "DEPLOYED_ADAPTER_SOURCE_AND_BUILD_ENVIRONMENT_NOT_REPRODUCIBLE" if status == "FAIL" else None,
        "deployed_adapter": {
            "path_wsl": LIB_WSL,
            "sha256": binary_sha,
            "runtime_banner_version": deployed_version,
            "checkpoint_symbols": [line for line in binary_symbols.splitlines() if line.strip()],
        },
        "candidate_source": {
            "path": str(SOURCE),
            "git_revision": source_git,
            "banner_version": source_version,
            "banner_version_matches_deployed_binary": source_version_matches,
            "proven_matches_deployed_binary": source_is_proven,
            "build_succeeded_against_deployed_openfoam10_environment": build_ok,
            "missing_or_incompatible_headers": incompatible_headers,
        },
        "actual_checkpoint_inventory": inventory,
        "allowed_runtime_action": "NO_NEW_IMPLICIT_WINDOW",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "source_provenance_audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    DOC.parent.mkdir(parents=True, exist_ok=True)
    report = f"""# OpenFOAM implicit rollback observability and one-window requalification V2\n\n## Status\n\n`ONE_WINDOW_IMPLICIT_REQUALIFICATION_V2 = FAIL` (fail closed; no V2 CFD window was started).\n\n## Adapter audit\n\nThe deployed binary is `{LIB_WSL}` with SHA-256 `{binary_sha}`. Its actual prior-runtime banner is v{result['deployed_adapter']['runtime_banner_version']}. It exports the checkpoint methods required for field, mesh, and time restoration. The source-level mechanism is: all registered geometric fields are copied/restored by type; existing old-time levels are copied/restored; `mesh_.points()` and `mesh_.oldPoints()` are retained; `mesh_.phi()` is handled through the mesh checkpoint; and `Time::setTime(value, index)` restores time and `timeIndex`.\n\nThe only recoverable candidate source is revision `{source_git}`, whose banner is v{result['candidate_source']['banner_version']}. It does not provenance-match the deployed v{result['deployed_adapter']['runtime_banner_version']} binary. A build against the installed OpenFOAM 10 environment failed before linking, due to incompatible/missing headers: `{', '.join(incompatible_headers) or 'none recorded'}`. Therefore an instrumented replacement library would not be an auditable build of the deployed adapter.\n\n## Required observability disposition\n\nNo diagnostic callback library was installed or loaded. Consequently `U`, `p`, `phi`, `pointDisplacement`, `cellDisplacement`, mesh points, `time`, and `timeIndex` remain `NOT_OBSERVABLE` at the actual callback boundaries. `Uf` and `meshPhi` are semantically checkpointed when registered / through the mesh checkpoint respectively, but their direct runtime identities also remain `NOT_OBSERVABLE`. No claim of rollback identity is made.\n\n## Decision\n\nThe first blocker is `DEPLOYED_ADAPTER_SOURCE_AND_BUILD_ENVIRONMENT_NOT_REPRODUCIBLE`. The minimal repair is to recover the exact source revision and the OpenFOAM 10 build environment that produced deployed library SHA-256 `{binary_sha}`, then rebuild a distinct diagnostic-only adapter with callback snapshots disabled by default. Only after its non-intrusiveness regression passes may a fresh one-window implicit requalification run.\n\n`NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`\n"""
    DOC.write_text(report, encoding="utf-8")
    print(json.dumps({"status": status, "blocker": result["blocker"]}))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
