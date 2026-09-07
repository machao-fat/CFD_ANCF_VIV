"""Create the OF10 lifecycle and data-read repair on top of diagnostic patch 0002.

This generator intentionally starts from the pinned upstream source plus the
existing diagnostic-only patch.  It produces a separate, reviewable patch and
never alters a prior diagnostic build or deployed adapter library.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one anchor, found {count}: {old[:80]!r}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: make_checkpoint_lifecycle_patch.py <diagnostic-source> "
            "<work-copy> <patch-0002> <patch-output>"
        )
    source, work, diagnostic_patch, output = map(Path, sys.argv[1:])
    if work.exists() or output.exists():
        raise RuntimeError("refusing to overwrite work-copy or lifecycle patch")
    diagnostic_source = work.parent / (work.name + "-diagnostic-base")
    if diagnostic_source.exists():
        raise RuntimeError("refusing to overwrite diagnostic-base work-copy")
    shutil.copytree(source, diagnostic_source)
    subprocess.run(["patch", "-p1", "-i", str(diagnostic_patch.resolve())], cwd=diagnostic_source, check=True)
    shutil.copytree(diagnostic_source, work)

    path = work / "Adapter.C"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "    precice_->initialize();\n    preciceInitialized_ = true;",
        "    precice_->initialize();\n"
        "    // Read initial coupling data after preCICE has completed its initial-data exchange.\n"
        "    // Displacement is a total field in the FSI module and must be available before\n"
        "    // the first tentative OpenFOAM solve.\n"
        "    readCouplingData(0.0);\n"
        "    preciceInitialized_ = true;",
    )
    text = replace_once(
        text,
        "    if (requiresWritingCheckpoint())\n    {\n        writeCheckpoint();\n    }\n\n    // As soon as OpenFOAM writes the results",
        "    if (requiresWritingCheckpoint())\n    {\n        writeCheckpoint();\n    }\n\n"
        "    // Apply the data made available by advance() before the next tentative solve.\n"
        "    // A rollback has already restored the window-start physical state above.\n"
        "    if (isCouplingOngoing())\n    {\n        readCouplingData(0.0);\n    }\n\n"
        "    // As soon as OpenFOAM writes the results",
    )
    text = replace_once(
        text,
        "    DEBUG(adapterInfo(\"Stored mesh points.\"));\n    if (mesh_.moving())\n    {\n        if (!meshCheckPointed)\n        {\n            // Set up the checkpoint for the mesh flux: meshPhi\n            setupMeshCheckpointing();\n            meshCheckPointed = true;\n        }\n        writeMeshCheckpoint();\n        writeVolCheckpoint(); // Does not write anything unless subcycling.\n    }",
        "    DEBUG(adapterInfo(\"Stored mesh points.\"));\n"
        "    // mesh_.moving() is false at the window-start checkpoint.  Nevertheless,\n"
        "    // a dynamic-mesh trial may create meshPhi, so register it through the\n"
        "    // normal fvMesh API before the checkpoint.\n"
        "    if (!meshCheckPointed)\n    {\n        setupMeshCheckpointing();\n        meshCheckPointed = true;\n    }\n    writeMeshCheckpoint();\n    writeVolCheckpoint(); // Does not write anything unless subcycling.",
    )
    text = text.replace("if (nOldTimes == 2)", "if (nOldTimes >= 2)")

    anchor = "    writeRollbackDiagnostic(\"CHECKPOINT_WRITE\");\n    ++rollbackDiagnosticIteration_;\n\n"
    preinitialize = r'''    // Stabilize old-time object lifetime before a tentative solve can create it.
    // This invokes the documented GeometricField::oldTime() API only on fields
    // that are already registered for checkpointing; no registry ownership is changed.
#define PRECICE_ENSURE_OLD_TIME(fields) \
    for (uint i = 0; i < fields.size(); ++i) \
    { \
        if (fields.at(i)->nOldTimes() == 0) \
        { \
            fields.at(i)->oldTime(); \
        } \
    }
    PRECICE_ENSURE_OLD_TIME(volScalarFields_);
    PRECICE_ENSURE_OLD_TIME(volVectorFields_);
    PRECICE_ENSURE_OLD_TIME(volTensorFields_);
    PRECICE_ENSURE_OLD_TIME(volSymmTensorFields_);
    PRECICE_ENSURE_OLD_TIME(surfaceScalarFields_);
    PRECICE_ENSURE_OLD_TIME(surfaceVectorFields_);
    PRECICE_ENSURE_OLD_TIME(surfaceTensorFields_);
    PRECICE_ENSURE_OLD_TIME(pointScalarFields_);
    PRECICE_ENSURE_OLD_TIME(pointVectorFields_);
    PRECICE_ENSURE_OLD_TIME(pointTensorFields_);
    PRECICE_ENSURE_OLD_TIME(meshSurfaceScalarFields_);
    PRECICE_ENSURE_OLD_TIME(meshSurfaceVectorFields_);
    PRECICE_ENSURE_OLD_TIME(meshVolVectorFields_);
#undef PRECICE_ENSURE_OLD_TIME

'''
    text = replace_once(text, anchor, preinitialize + anchor)

    copies_anchor = "    // NOTE: Add here other types to write, if needed.\n"
    store_histories = r'''    // Checkpoint numerical values of all pre-existing old-time levels.  The
    // lifecycle above makes their existence deterministic before trial #1.
#define PRECICE_STORE_OLD_TIME(fields, copies) \
    for (uint i = 0; i < fields.size(); ++i) \
    { \
        const int oldTimes(fields.at(i)->nOldTimes()); \
        if (oldTimes >= 1) \
        { \
            copies.at(i)->oldTime() == fields.at(i)->oldTime(); \
        } \
        if (oldTimes >= 2) \
        { \
            copies.at(i)->oldTime().oldTime() == fields.at(i)->oldTime().oldTime(); \
        } \
    }
    PRECICE_STORE_OLD_TIME(volScalarFields_, volScalarFieldCopies_);
    PRECICE_STORE_OLD_TIME(volVectorFields_, volVectorFieldCopies_);
    PRECICE_STORE_OLD_TIME(volTensorFields_, volTensorFieldCopies_);
    PRECICE_STORE_OLD_TIME(volSymmTensorFields_, volSymmTensorFieldCopies_);
    PRECICE_STORE_OLD_TIME(surfaceScalarFields_, surfaceScalarFieldCopies_);
    PRECICE_STORE_OLD_TIME(surfaceVectorFields_, surfaceVectorFieldCopies_);
    PRECICE_STORE_OLD_TIME(surfaceTensorFields_, surfaceTensorFieldCopies_);
    PRECICE_STORE_OLD_TIME(pointScalarFields_, pointScalarFieldCopies_);
    PRECICE_STORE_OLD_TIME(pointVectorFields_, pointVectorFieldCopies_);
    PRECICE_STORE_OLD_TIME(pointTensorFields_, pointTensorFieldCopies_);
    PRECICE_STORE_OLD_TIME(meshSurfaceScalarFields_, meshSurfaceScalarFieldCopies_);
    PRECICE_STORE_OLD_TIME(meshSurfaceVectorFields_, meshSurfaceVectorFieldCopies_);
    PRECICE_STORE_OLD_TIME(meshVolVectorFields_, meshVolVectorFieldCopies_);
#undef PRECICE_STORE_OLD_TIME

'''
    text = replace_once(text, copies_anchor, store_histories + copies_anchor)
    path.write_text(text, encoding="utf-8")

    result = subprocess.run(
        ["diff", "-ruN", "--label", "a/Adapter.C", "--label", "b/Adapter.C",
         str(diagnostic_source / "Adapter.C"), str(path)],
        capture_output=True, text=True,
    )
    output.write_text(result.stdout, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
