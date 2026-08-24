#!/usr/bin/env python3
"""Generate one independent parameterized OpenFOAM slice case."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _number(value: float) -> str:
    return format(float(value), ".12g")


FORBIDDEN_NAMES = {
    "forces.dat",
    "forceCoeffs.dat",
    "motion_ready",
    "load_ready",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_tree(source: Path, target: Path) -> list[str]:
    """Copy one explicitly allowed tree and return copied relative paths."""

    if not source.is_dir():
        raise SystemExit(f"required reference directory does not exist: {source}")
    shutil.copytree(source, target)
    return [str(path.relative_to(target)).replace("\\", "/")
            for path in target.rglob("*") if path.is_file()]


def _assert_clean_case(output: Path, *, target_time: str) -> None:
    """Reject any artifact which could make a real process look fresh."""

    forbidden = []
    for path in output.rglob("*"):
        relative = path.relative_to(output)
        parts = relative.parts
        name = path.name
        if any(part.startswith("processor") for part in parts):
            forbidden.append(str(relative))
        if name in FORBIDDEN_NAMES or name.startswith("motion_consumed_"):
            forbidden.append(str(relative))
        if name.startswith("log.") or name.endswith(".log"):
            forbidden.append(str(relative))
        if "postProcessing" in parts and path.is_file():
            forbidden.append(str(relative))
        if "coupling" in parts and path.is_file():
            forbidden.append(str(relative))
        if "checkpoints" in parts:
            forbidden.append(str(relative))
    target = output / target_time
    if target.is_dir() and target_time != "0":
        forbidden.append(str(target.relative_to(output)))
    if forbidden:
        raise SystemExit("generated case is not clean: " + ", ".join(sorted(set(forbidden))))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-case", type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--slice-id", type=int, required=True)
    parser.add_argument("--s-ref-m", type=float, required=True)
    parser.add_argument("--slice-length-m", type=float, required=True)
    parser.add_argument("--unit-span-m", type=float, default=1.0)
    parser.add_argument("--start-time", type=float, default=0.0)
    parser.add_argument("--end-time", type=float, required=True)
    parser.add_argument("--delta-t", type=float, required=True)
    parser.add_argument("--exchange-dir", default="coupling")
    parser.add_argument("--motion-input", default="coupling/motion.csv")
    parser.add_argument("--load-output", default="postProcessing/cylinderForces")
    parser.add_argument("--slice-manifest-sha256", default="")
    parser.add_argument("--config-sha256", default="")
    parser.add_argument("--cfd-diameter-m", type=float, default=1.0)
    parser.add_argument("--freestream-mps", type=float, default=1.0)
    parser.add_argument("--fluid-density-kgpm3", type=float, default=1000.0)
    parser.add_argument("--kinematic-viscosity-m2ps", type=float, default=0.01)
    parser.add_argument("--ancf-length-m", type=float, default=10.0)
    parser.add_argument("--ancf-diameter-m", type=float, default=1.0)
    parser.add_argument("--ancf-inner-diameter-m", type=float, default=0.9)
    parser.add_argument("--youngs-modulus-pa", type=float, default=2.07e11)
    parser.add_argument("--top-tension-n", type=float, default=1.0e7)
    parser.add_argument(
        "--initial-time", default="0",
        help="selected reference time directory for a recorded warm start (default: 0)",
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--static-mesh", action="store_true",
                        help="render a fixed-mesh warm-up case instead of the motion bridge")
    parser.add_argument("--step-offset", type=int, default=0)
    args = parser.parse_args()
    if args.slice_id < 0 or args.s_ref_m < 0 or args.slice_length_m <= 0 or args.unit_span_m <= 0:
        raise SystemExit("slice identity/length/span values are invalid")
    if args.start_time < 0 or args.end_time < args.start_time or args.delta_t <= 0:
        raise SystemExit("start/end/delta-t values are invalid")
    if args.step_offset < 0:
        raise SystemExit("step-offset must be non-negative")
    if min(args.cfd_diameter_m, args.freestream_mps, args.fluid_density_kgpm3,
           args.kinematic_viscosity_m2ps, args.ancf_length_m, args.ancf_diameter_m,
           args.youngs_modulus_pa, args.top_tension_n) <= 0:
        raise SystemExit("physical parameters must be strictly positive")
    if args.ancf_inner_diameter_m < 0 or args.ancf_inner_diameter_m >= args.ancf_diameter_m:
        raise SystemExit("ANCF inner diameter must be non-negative and smaller than outer diameter")
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {args.output}")
    if args.reference_case and not args.reference_case.is_dir():
        raise SystemExit(f"reference case does not exist: {args.reference_case}")
    args.output.mkdir(parents=True)

    # A reference case is an input source, never a directory to copy wholesale.
    # In particular, postProcessing, coupling, old time directories, logs and
    # runtime checkpoints are deliberately outside this whitelist.
    copied_files: list[str] = []
    source = args.reference_case.resolve() if args.reference_case else None
    if source is not None:
        for directory in ("constant", "system"):
            copied_files.extend(_copy_tree(source / directory, args.output / directory))
        initial_source = source / args.initial_time
        if initial_source.is_dir():
            copied_files.extend(_copy_tree(initial_source, args.output / args.initial_time))
            if abs(float(args.initial_time) - args.start_time) > 1.0e-12 * max(1.0, abs(args.start_time)):
                raise SystemExit("start-time must equal the selected warm-start time")
        elif args.initial_time != "0":
            raise SystemExit(f"selected initial time directory does not exist: {initial_source}")
        # motionScale is case-level static data.  Copy only that one required
        # file when a non-zero warm-start time was selected.
        source_motion_scale = source / "0" / "motionScale"
        if source_motion_scale.is_file():
            target_motion_scale = args.output / "0" / "motionScale"
            target_motion_scale.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_motion_scale, target_motion_scale)
            copied_files.append("0/motionScale")
    else:
        # The checked-in template contains only dictionary fragments.  A real
        # case must supply its mesh/fields through an explicit reference case.
        # The no-reference path remains useful for dictionary unit tests.
        for directory in ("constant", "system"):
            (args.output / directory).mkdir(parents=True, exist_ok=True)
    exchange = args.output / args.exchange_dir
    for relative in ("motion", "load", "consumed"):
        (exchange / relative).mkdir(parents=True, exist_ok=True)
    (args.output / args.load_output).mkdir(parents=True, exist_ok=True)
    (args.output / "postProcessing").mkdir(parents=True, exist_ok=True)
    # Do not create a log placeholder.  A process-owned log must be created by
    # the current OpenFOAM invocation and is part of the run provenance.

    replacements = {
        "{{CASE_ID}}": args.case_id,
        "{{SLICE_ID}}": str(args.slice_id),
        "{{S_REF_M}}": _number(args.s_ref_m),
        "{{SLICE_LENGTH_M}}": _number(args.slice_length_m),
        "{{UNIT_SPAN_M}}": _number(args.unit_span_m),
        "{{START_TIME_S}}": _number(args.start_time),
        "{{END_TIME_S}}": _number(args.end_time),
        "{{DELTA_T_S}}": _number(args.delta_t),
        "{{STEP_OFFSET}}": str(args.step_offset),
        "{{EXCHANGE_DIR}}": args.exchange_dir.replace("\\", "/"),
        "{{MOTION_INPUT}}": args.motion_input.replace("\\", "/"),
        "{{LOAD_OUTPUT}}": args.load_output.replace("\\", "/"),
    }
    for relative in ("constant/dynamicMeshDict", "system/controlDict"):
        template = ROOT / "case_template" / f"{relative}.in"
        target = args.output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = template.read_text(encoding="utf-8")
        for source, replacement in replacements.items():
            content = content.replace(source, replacement)
        if args.static_mesh and relative == "constant/dynamicMeshDict":
            content = 'FoamFile\n{\n    format ascii;\n    class dictionary;\n    location "constant";\n    object dynamicMeshDict;\n}\n\ndynamicFvMesh staticFvMesh;\n'
        target.write_text(content, encoding="utf-8")
    _assert_clean_case(args.output, target_time=_number(args.end_time))
    provenance = {
        "schema_version": "stage4b-v3-case-provenance",
        "run_id": args.run_id or None,
        "source_case": str(source) if source is not None else None,
        "source_initial_time": args.initial_time if source is not None else None,
        "static_mesh_warmup": bool(args.static_mesh),
        "step_offset": args.step_offset,
        "start_time_s": args.start_time,
        "copy_whitelist": ["constant", "system", args.initial_time, "0/motionScale"],
        "copied_files": sorted(set(copied_files)),
        "initial_file_sha256": {
            relative: _sha256_file(args.output / relative)
            for relative in sorted(set(copied_files))
            if (args.output / relative).is_file()
        },
    }
    (args.output / "case_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    config = {
        "schema_version": "0.2.1", "case_id": args.case_id,
        "protocol": "Stage4-Multislice",
        "slice_id": args.slice_id, "s_ref_m": args.s_ref_m,
        "slice_length_m": args.slice_length_m, "unit_span_m": args.unit_span_m,
        "start_time_s": args.start_time, "end_time_s": args.end_time,
        "delta_t_s": args.delta_t, "exchange_dir": args.exchange_dir,
        "motion_input": args.motion_input, "load_output": args.load_output,
        "step_offset": args.step_offset,
        "slice_manifest_sha256": args.slice_manifest_sha256,
        "config_sha256": args.config_sha256,
        "motionScale_relative_path": "0/motionScale",
        "run_id": args.run_id or "",
        "source_initial_time": args.initial_time if source is not None else None,
        "cfd": {
            "diameter_m": args.cfd_diameter_m,
            "freestream_mps": args.freestream_mps,
            "rho_kgpm3": args.fluid_density_kgpm3,
            "nu_m2ps": args.kinematic_viscosity_m2ps,
        },
        "ancf": {
            "length_m": args.ancf_length_m,
            "outer_diameter_m": args.ancf_diameter_m,
            "inner_diameter_m": args.ancf_inner_diameter_m,
            "youngs_modulus_pa": args.youngs_modulus_pa,
            "top_tension_n": args.top_tension_n,
        },
    }
    (args.output / "multi_slice_case_config.json").write_text(
        json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "generated", "case": str(args.output), "config": config}, sort_keys=True))


if __name__ == "__main__":
    main()
