"""Generate the sole registry-safe OF10 rollback candidate on diagnostic patch 0002."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one anchor: {old[:80]!r}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit("usage: make_registry_safe_patch.py <source> <work> <patch-0002> <output>")
    source, work, diagnostic_patch, output = map(Path, sys.argv[1:])
    diagnostic = work.parent / (work.name + "-diagnostic-base")
    if work.exists() or diagnostic.exists() or output.exists():
        raise RuntimeError("refusing to overwrite lifecycle work or patch")
    shutil.copytree(source, diagnostic)
    subprocess.run(["patch", "-p1", "-i", str(diagnostic_patch.resolve())], cwd=diagnostic, check=True)
    shutil.copytree(diagnostic, work)
    adapter = work / "Adapter.C"
    text = adapter.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    precice_->initialize();\n    preciceInitialized_ = true;",
        "    precice_->initialize();\n"
        "    // Initial data has now been exchanged. Apply total displacement before\n"
        "    // the first tentative OpenFOAM solve.\n"
        "    readCouplingData(0.0);\n"
        "    preciceInitialized_ = true;",
    )
    text = replace_once(
        text,
        "    if (requiresWritingCheckpoint())\n    {\n        writeCheckpoint();\n    }\n\n    // As soon as OpenFOAM writes the results",
        "    if (requiresWritingCheckpoint())\n    {\n        writeCheckpoint();\n    }\n\n"
        "    // advance() makes the next total displacement available. If a rollback\n"
        "    // occurred above, the physical state has already been restored first.\n"
        "    if (isCouplingOngoing())\n    {\n        readCouplingData(0.0);\n    }\n\n"
        "    // As soon as OpenFOAM writes the results",
    )
    text = replace_once(
        text,
        "    const_cast<fvMesh&>(mesh_).movePoints(meshPoints_);\n\n    DEBUG(adapterInfo(\"Moved mesh points to their previous locations.\"));",
        "    const_cast<fvMesh&>(mesh_).movePoints(meshPoints_);\n\n"
        "    // meshPhi is a derived OF10 mesh-motion flux, created by movePoints().\n"
        "    // Do not create or delete registry objects at the window-start checkpoint.\n"
        "    // Once a trial has created it, this normal API access reconstructs its\n"
        "    // restored-time value (zero on the restored time layer when appropriate).\n"
        "    if (mesh_.foundObject<surfaceScalarField>(\"meshPhi\"))\n    {\n        mesh_.phi();\n    }\n\n"
        "    DEBUG(adapterInfo(\"Moved mesh points to their previous locations.\"));",
    )
    adapter.write_text(text, encoding="utf-8")
    diff = subprocess.run(
        ["diff", "-ruN", "--label", "a/Adapter.C", "--label", "b/Adapter.C",
         str(diagnostic / "Adapter.C"), str(adapter)], capture_output=True, text=True,
    )
    output.write_text(diff.stdout, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
