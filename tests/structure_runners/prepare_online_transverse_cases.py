from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.coupling.file_exchange.csv_contract import MOTION_REQUIRED
from src.coupling.online_file_coupling.protocol import publish_ready


DEFAULT_SOURCE = (
    ROOT
    / "cases"
    / "openfoam"
    / "fixed_cylinder_study_full30b"
    / "medium_dt0p0025"
)
DEFAULT_TEMPLATE = ROOT / "cases" / "openfoam" / "single_slice_eb_fsi"
DEFAULT_DESTINATIONS = {
    "eb": ROOT / "cases" / "openfoam" / "single_slice_eb_transverse150_prepared",
    "ancf": ROOT / "cases" / "openfoam" / "single_slice_ancf_transverse150_prepared",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replace_scalar(text: str, name: str, value: str) -> str:
    pattern = rf"(?m)^(\s*{re.escape(name)}\s+)[^;]+;"
    changed, count = re.subn(pattern, rf"\g<1>{value};", text)
    if count != 1:
        raise ValueError(f"expected exactly one {name} entry, found {count}")
    return changed


def convert_developed_velocity_to_moving_wall(text: str, source_time: str) -> str:
    text = re.sub(
        rf'(?m)^(\s*location\s+)"?{re.escape(source_time)}"?;',
        r'\g<1>"0";',
        text,
        count=1,
    )
    cylinder = re.compile(r"(?ms)(^\s*cylinder\s*\{)(.*?)(^\s*\})")
    match = cylinder.search(text)
    if match is None:
        raise ValueError("developed U field has no cylinder boundary block")
    body = match.group(2)
    if "type            noSlip;" not in body and "type noSlip;" not in body:
        raise ValueError("developed U cylinder is not the expected fixed noSlip patch")
    body = re.sub(
        r"(?m)^[ \t]*type[ \t]+noSlip[ \t]*;[ \t]*$",
        "        type            movingWallVelocity;",
        body,
    )
    if not re.search(r"(?m)^\s*value\s+", body):
        body = body.rstrip() + "\n        value           uniform (0 0 0);\n"
    return text[: match.start()] + match.group(1) + body + match.group(3) + text[match.end() :]


def reset_field_location(text: str, source_time: str) -> str:
    return re.sub(
        rf'(?m)^(\s*location\s+)"?{re.escape(source_time)}"?;',
        r'\g<1>"0";',
        text,
        count=1,
    )


def write_seed_motion(case_dir: Path, s_ref_m: float) -> None:
    coupling = case_dir / "coupling"
    (coupling / "consumed").mkdir(parents=True)
    motion = coupling / "motion.csv"
    row = {
        "schema_version": "0.1.0",
        "step": 0,
        "coupling_iteration": 0,
        "time_s": 0.0,
        "slice_id": 0,
        "s_ref_m": s_ref_m,
        "x_m": 0.0,
        "y_m": 0.0,
        "z_m": s_ref_m,
        "vx_mps": 0.0,
        "vy_mps": 0.0,
        "vz_mps": 0.0,
        "ax_mps2": 0.0,
        "ay_mps2": 0.0,
        "az_mps2": 0.0,
    }
    with motion.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=MOTION_REQUIRED)
        writer.writeheader()
        writer.writerow(row)
    publish_ready(
        motion,
        coupling / "motion_ready",
        kind="motion",
        expected_s_ref_m=[s_ref_m],
    )


def prepare_one(
    *, branch: str, source: Path, source_time: str, template: Path, destination: Path
) -> dict[str, object]:
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing case: {destination}")
    source_time_dir = source / source_time
    required = [
        source / "constant" / "polyMesh",
        source_time_dir / "U",
        source_time_dir / "p",
        template / "system",
        template / "constant" / "dynamicMeshDict",
        template / "0" / "pointMotionUx",
        template / "0" / "motionScale",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing preparation inputs: {missing}")

    destination.mkdir(parents=True)
    shutil.copytree(source / "constant", destination / "constant")
    shutil.copytree(template / "system", destination / "system")
    (destination / "0").mkdir()
    shutil.copy2(template / "0" / "pointMotionUx", destination / "0" / "pointMotionUx")
    shutil.copy2(template / "0" / "motionScale", destination / "0" / "motionScale")
    shutil.copy2(
        template / "constant" / "dynamicMeshDict",
        destination / "constant" / "dynamicMeshDict",
    )

    u_text = (source_time_dir / "U").read_text(encoding="utf-8")
    u_text = convert_developed_velocity_to_moving_wall(u_text, source_time)
    (destination / "0" / "U").write_text(u_text, encoding="utf-8")
    p_text = (source_time_dir / "p").read_text(encoding="utf-8")
    p_text = reset_field_location(p_text, source_time)
    (destination / "0" / "p").write_text(p_text, encoding="utf-8")

    control = (destination / "system" / "controlDict").read_text(encoding="utf-8")
    control = replace_scalar(control, "startTime", "0")
    control = replace_scalar(control, "endTime", "0.25")
    control = replace_scalar(control, "deltaT", "0.0025")
    (destination / "system" / "controlDict").write_text(control, encoding="utf-8")

    dynamic = (destination / "constant" / "dynamicMeshDict").read_text(encoding="utf-8")
    dynamic = replace_scalar(dynamic, "couplingDeltaT", "0.0025")
    (destination / "constant" / "dynamicMeshDict").write_text(dynamic, encoding="utf-8")
    write_seed_motion(destination, 75.0)

    return {
        "branch": branch,
        "path": str(destination),
        "mesh_points_sha256": sha256(destination / "constant" / "polyMesh" / "points"),
        "initial_U_sha256": sha256(destination / "0" / "U"),
        "initial_p_sha256": sha256(destination / "0" / "p"),
        "cylinder_velocity_boundary": "movingWallVelocity",
        "prepared_end_step": 100,
        "prepared_end_time_s": 0.25,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare, but do not execute, the EB/ANCF transverse-only online A/B cases."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--source-time", default="30")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT
        / "results"
        / "04_eb_ancf_physical_comparison"
        / "online_transverse_prepared_manifest.json",
    )
    args = parser.parse_args()

    records = []
    for branch, destination in DEFAULT_DESTINATIONS.items():
        records.append(
            prepare_one(
                branch=branch,
                source=args.source.resolve(),
                source_time=args.source_time,
                template=args.template.resolve(),
                destination=destination,
            )
        )

    if records[0]["mesh_points_sha256"] != records[1]["mesh_points_sha256"]:
        raise RuntimeError("prepared EB and ANCF meshes differ")
    if records[0]["initial_U_sha256"] != records[1]["initial_U_sha256"]:
        raise RuntimeError("prepared EB and ANCF initial U fields differ")
    if records[0]["initial_p_sha256"] != records[1]["initial_p_sha256"]:
        raise RuntimeError("prepared EB and ANCF initial p fields differ")

    manifest = {
        "status": "prepared_not_run",
        "source": {
            "case": str(args.source.resolve()),
            "time": args.source_time,
            "source_U_sha256": sha256(args.source / args.source_time / "U"),
            "source_p_sha256": sha256(args.source / args.source_time / "p"),
            "note": "Developed fixed-cylinder field; target U cylinder patch is intentionally converted from noSlip to movingWallVelocity.",
        },
        "structure": {
            "L_m": 150.0,
            "D_m": 1.0,
            "dInner_m": 0.9,
            "nElem": 10,
            "nSlices": 1,
            "s_ref_m": [75.0],
            "topTension_N": 1.0e6,
            "youngs_modulus_Pa": 2.07e11,
            "body_forces_enabled": False,
            "rayleigh_alpha_1ps": 0.019477603534520972,
            "rayleigh_beta_s": 0.0,
            "target_first_mode_damping_ratio": 0.01,
        },
        "coupling": {
            "dt_s": 0.0025,
            "load_mode": "transverse_only",
            "raw_cfd_force_preserved": True,
            "applied_structure_force": "[0,Fy,0]",
            "force_representation": "integrated_N",
            "rhoInf_kgpm3": 1000.0,
            "unit_span_m": 1.0,
            "slice_length_m": 1.0,
            "interpretation": "OpenFOAM kinematic-pressure force multiplied by rhoInf and integrated over one metre span; one integrated slice force at s=75 m.",
        },
        "cases": records,
        "execution_order": [
            "Run EB smoke only (100 steps, 0.25 s).",
            "Audit CFL, mesh, x=0, raw/applied force, displacement and energy.",
            "Only after EB smoke passes, run ANCF from its untouched identical initial case.",
            "If both smoke tests pass, prepare fresh identical cases for a longer sequential A/B; never continue the smoke-mutated cases as the formal comparison.",
        ],
        "blocking_protocol_fix": "publish_load_from_forces.py must accept s_ref_m=75 and continuous_fsi_driver must pass it before execution.",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
