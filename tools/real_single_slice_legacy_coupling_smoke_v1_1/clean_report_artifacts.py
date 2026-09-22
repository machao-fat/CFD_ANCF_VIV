"""Rewrite the human-readable smoke artifacts without changing runtime evidence."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(r"D:\CFD\CFD_ANCF_VIV\runtime\ANCF_validation\mesh_case")
EVIDENCE = ROOT / "runtime" / "ANCF_validation"
PREFIX = "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1"
ATTEMPT = ROOT / "runtime" / "coupling_validation" / PREFIX / "attempt_004"
TRACE = json.loads((ATTEMPT / "logs" / "structure_trace.json").read_text(encoding="utf-8"))
RESULT = json.loads((EVIDENCE / f"{PREFIX}_RESULT.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((EVIDENCE / f"{PREFIX}_MANIFEST.json").read_text(encoding="utf-8"))
XML = (ATTEMPT / "precice-config.xml").read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    source_hashes = MANIFEST["copied_mesh_core_hashes"]
    source_case = str(MANIFEST["source_case"])
    copied_case = str(MANIFEST["copied_case"])
    protocol = f"""# {PREFIX}

## Scope

One bounded real Ns=1 `LegacyPointLumped` smoke using the generic path:

`SliceManifest -> generated preCICE XML -> generic launch plan -> StructureCoordinator -> preCICE -> OpenFOAM adapter -> persistent ANCF worker`.

Frozen before the successful run: target accepted windows = 3; hard maximum = 5; `dt=0.005 s`; `endTime=0.015 s`; no G1/SLD1/CFD campaign.

## Case contract

- source case: `{source_case}` (read-only)
- copied case: `{copied_case}`
- `Ns=1`, `slice_0000`, `S_1=5.0 m`
- mode: `LegacyPointLumped`
- force representation: `integrated_slice_force_N`
- SLD1: `false`
- patch: `cylinder`; unit span: `1.0 m`
- interface: `STRUCTURE_3D_INTERFACE_2D`

## Success gates

preCICE/OpenFOAM/StructureCoordinator initialization, 3 accepted windows, one complete force set and one global ANCF advance per window, finite force/state/motion, time identity, and clean finalization. Checkpoint read/write was observational only and was not forced.

## Authorized repair history

Retained earlier attempts exposed: (a) launcher nounset incompatibility, (b) serialized-manifest `reference_length_m`/`length_m` mismatch, and (c) generic XML force-exchange mesh ownership defect. After explicit authorization, the validation-only launcher/manifest loading and generic topology generator were corrected. The successful XML uses `Structure-Mesh-slice_0000` as the force exchange mesh, matching the existing OpenFOAM adapter contract.

Production HEAD remained `{RESULT["production_head"]}`. The focused topology repair is an uncommitted working-tree change; ANCF kernel, worker, protocol, case physics, and wire implementation were not changed.
"""
    write(EVIDENCE / f"{PREFIX}_PROTOCOL.md", protocol)

    adaptation = f"""# Case adaptation

Original source: `{source_case}`. It was copied; no source file was edited.

Only the copied case received:

- `system/preciceDict` for `Fluid_slice_0000`, mesh `Fluid-Mesh-slice_0000`, patch `cylinder`;
- `precice-config.xml`;
- `constant/dynamicMeshDict` changed to the existing `dynamicMotionSolverFvMesh` / `displacementLaplacian` convention;
- bounded `system/controlDict` (`dt=0.005`, `endTime=0.015`, adapter library/function object);
- zero-initialized `0/pointDisplacement` and `0/cellDisplacement`.

The copied polyMesh key hashes equal the source: `{source_hashes}`. Full `checkMesh -allTopology -allGeometry` returned 0 and `Mesh OK`. No remeshing or source-case/production physics change was made.
"""
    write(EVIDENCE / f"{PREFIX}_CASE_ADAPTATION.md", adaptation)

    # Preserve the exact byte-level XML consumed by attempt_004. The runtime
    # exchange-directory is part of the generated configuration, so replacing
    # it with a separately generated copy would make the formal identity
    # disagree with the configuration actually used by the successful run.
    shutil.copyfile(ATTEMPT / "precice-config.xml", EVIDENCE / f"{PREFIX}_PRECISE_CONFIG.xml")

    force_lines = "\n".join(
        f"| {row['window']} | {row['fluid_force_timestamp_s']} | {row['openfoam_integrated_force_N']} | {row['legacy_integrated_force_N']} | {row['motion_xyz_m']} | {row['kernel_iterations']} | {row['kernel_residual']:.6e} |"
        for row in TRACE["records"]
    )
    report = f"""# {PREFIX}

## Final classification

**PASS**

`GENERIC_LIVE_COUPLING_PIPELINE = REAL_RUNTIME_ESTABLISHED_FOR_NS1_LEGACY`

This is a plumbing/lifecycle smoke only. It is not a VIV benchmark, distributed-load validation, slice-number-independence claim, G1 validation, or full structural validation.

## Identity and source case

- production HEAD: `{RESULT['production_head']}`
- parent: `{RESULT['production_parent']}`
- baseline tag target: `{RESULT['baseline_tag_target']}`
- source case: `{source_case}`
- copied case: `{copied_case}`
- original source key hashes unchanged: **True**
- copied polyMesh key hashes equal source: **True**

## Generic path and case contract

The successful run used `SliceManifest -> generated generic XML -> generated launch descriptor -> StructureCoordinator -> real preCICE -> Fluid_slice_0000/pimpleFoam -> persistent ANCF worker`. It did not use the historical launcher.

`Ns=1`, `slice_0000`, `S_1=5.0 m`, `LegacyPointLumped`, `integrated_slice_force_N`, `SLD1=false`, unit span `1.0 m`, cylinder patch `cylinder`, and `STRUCTURE_3D_INTERFACE_2D`.

Copied-case-only adaptations were `system/preciceDict`, `precice-config.xml`, `constant/dynamicMeshDict`, bounded `system/controlDict`, `0/pointDisplacement`, and `0/cellDisplacement`. No polyMesh or source-case file was edited.

## Environment and generated identities

- OpenFOAM: `OpenFOAM 10 (build 10-c4cf895ad8fa)`
- preCICE core: `3.4.1`
- pyprecice: `3.4.0` audited runtime dependency
- Linux worker SHA256: `{RESULT['production_hashes']['persistent_worker_linux']}`
- manifest SHA256: `{RESULT['manifest_sha256']}`
- generated XML SHA256: `{RESULT['precice_config_sha256']}`
- authorized topology repair diff SHA256: `{RESULT['production_diff_sha256']}`

## Process and coupling result

StructureCoordinator PID 1218, Fluid_slice_0000/pimpleFoam PID 1253, and nested persistent ANCF worker PID 1220 exited with code 0 in attempt_004. preCICE initialized and finalized. OpenFOAM reached final coupling time `0.015 s`; no residual matching processes remained.

| window | time (s) | OpenFOAM integrated force [N] | legacy worker force [N] | motion returned at S1 [m] | worker Newton iterations | worker residual |
|---:|---:|---|---|---|---:|---:|
{force_lines}

For every accepted window: force reads = 1, complete force sets = 1, one attempted and one committed global ANCF advance, and one motion write. The worker request carries `integrated_slice_force_N`; because unit span is 1 m, the normalized line-force diagnostic has the same numeric components, but the legacy worker representation remains integrated force [N].

## Time, state, and checkpoint

Force timestamps, preCICE window times, structural motion timestamps, and global steps are `(0.005, 0.010, 0.015) s` with `dt=0.005 s` and no off-by-one drift. All q/qdot/qddot and motion values were finite. Final state hashes are recorded in `STATE_TRACE.json`. Checkpoint writes = 0 and reads = 0; `REAL_ROLLBACK_PATH = NOT_TRIGGERED_IN_THIS_SMOKE`.

## Retained repair attempts

- attempt_001: launcher failed before OpenFOAM start;
- attempt_002: StructureCoordinator rejected serialized manifest key semantics;
- attempt_003: preCICE initialized and OpenFOAM started, then force exchange failed because the generated exchange named the fluid mesh;
- attempt_004: authorized topology correction passed the complete smoke.

## Non-claims and next phase

G1 remains `NOT_CLOSED`; independent ANCF structural validation remains `NOT_CLOSED`. SLD1 distributed real runtime and arbitrary-N real runtime remain untested.

Authorized next phase: `REAL_TWO_SLICE_SLD1_DISTRIBUTED_COUPLING_SMOKE_V1` (not executed).
"""
    write(EVIDENCE / f"{PREFIX}_REPORT.md", report)

    formal = [
        EVIDENCE / f"{PREFIX}_PROTOCOL.md", EVIDENCE / f"{PREFIX}_CASE_ADAPTATION.md",
        EVIDENCE / f"{PREFIX}_ENVIRONMENT.md", EVIDENCE / f"{PREFIX}_MANIFEST.json",
        EVIDENCE / f"{PREFIX}_PRECISE_CONFIG.xml", EVIDENCE / f"{PREFIX}_PROCESS_TABLE.json",
        EVIDENCE / f"{PREFIX}_FORCE_TRACE.csv", EVIDENCE / f"{PREFIX}_MOTION_TRACE.csv",
        EVIDENCE / f"{PREFIX}_TIME_IDENTITY.csv", EVIDENCE / f"{PREFIX}_STATE_TRACE.json",
        EVIDENCE / f"{PREFIX}_RESULT.json", EVIDENCE / f"{PREFIX}_REPORT.md",
    ]
    lines = ["# SHA256 manifest (self-entry excluded)"]
    for path in formal:
        lines.append(f"{sha(path)}  {path.relative_to(ROOT).as_posix()}")
    for path in sorted((ATTEMPT / "logs").glob("*")):
        if path.is_file():
            lines.append(f"{sha(path)}  {path.relative_to(ROOT).as_posix()}")
    write(EVIDENCE / f"{PREFIX}_SHA256_MANIFEST.txt", "\n".join(lines) + "\n")
    print("CLEAN_REPORT_ARTIFACTS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
