"""Fail-closed evidence check for the reproducible OpenFOAM 10 adapter baseline.

This test deliberately does not start a preCICE coupling or an ANCF worker.
It verifies two clean-build artifacts and the already-recorded OpenFOAM-only
loader, zero-motion, small-motion, and legacy/new load-only A/B probes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "reproducible_openfoam10_adapter_baseline_recovery_v1"
RESULT = ROOT / "results" / "reproducible_openfoam10_adapter_baseline_recovery_v1" / "noncoupled_regression.json"
WSL = Path(r"\\wsl$\Ubuntu-22.04\home\machao\OpenFOAM\reproducible_adapter_baseline_v1")
EXPECTED_LIBRARY_SHA256 = "5e5cb644a072c7eee87217f674b57a1421b66c13fc5817d1d51b684884350ede"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(path: Path) -> Path:
    if not path.is_file():
        raise RuntimeError(f"missing required evidence: {path}")
    return path


def main() -> int:
    if RESULT.exists():
        raise RuntimeError(f"refusing to overwrite immutable evidence: {RESULT}")
    build_d = require(WSL / "build_d" / "lib" / "libpreciceAdapterFunctionObject.so")
    build_e = require(WSL / "build_e" / "lib" / "libpreciceAdapterFunctionObject.so")
    small = RUNTIME / "small_motion"
    legacy = RUNTIME / "small_motion_legacy"
    zero_log = require(RUNTIME / "zero_motion" / "baseline_zero_motion.stdout").read_text(encoding="utf-8", errors="replace")
    small_log = require(small / "baseline_small_motion.stdout").read_text(encoding="utf-8", errors="replace")
    legacy_log = require(legacy / "baseline_small_motion_legacy.stdout").read_text(encoding="utf-8", errors="replace")
    constructor_log = require(RUNTIME / "function_object_construction" / "function_object_execute.stdout").read_text(encoding="utf-8", errors="replace")

    equal_paths = ("0.005/U", "0.005/p", "0.005/polyMesh/points", "postProcessing/cylinderForces/0/forces.dat")
    ab = {item: {"new": sha256(require(small / item)), "legacy": sha256(require(legacy / item))} for item in equal_paths}
    ab_pass = all(item["new"] == item["legacy"] for item in ab.values())
    fatal = lambda text: "FOAM FATAL ERROR" in text or "Floating point exception" in text
    rows = {
        "clean_builds": {
            "build_d_sha256": sha256(build_d),
            "build_e_sha256": sha256(build_e),
            "byte_identical": build_d.read_bytes() == build_e.read_bytes(),
        },
        "zero_motion_dynamic_startup": {
            "completed": "End" in zero_log and not fatal(zero_log),
            "ordinary_cell_displacement_solve_observed": "Solving for cellDisplacementx" in zero_log,
        },
        "small_prescribed_motion": {
            "completed": "End" in small_log and not fatal(small_log),
            "force_decomposition_observed": "forces cylinderForces write:" in small_log,
            "point_displacement_written": (small / "0.005" / "pointDisplacement").is_file(),
            "mesh_points_written": (small / "0.005" / "polyMesh" / "points").is_file(),
        },
        "load_only_ab": {"paths": ab, "pass": ab_pass},
        "function_object_construction": {
            "adapter_banner_observed": "Loaded the OpenFOAM-preCICE adapter - v1.3.0." in constructor_log,
            "read_precice_dict_observed": "Reading preciceDict" in constructor_log,
            "expected_negative_config": "No module is enabled." in constructor_log,
            "no_participant_initialized": "preCICE was configured and initialized" not in constructor_log,
            "note": "The intentionally empty-module configuration is a constructor-only negative control; it must terminate before any preCICE initialize/advance.",
        },
    }
    clean = rows["clean_builds"]
    zero = rows["zero_motion_dynamic_startup"]
    small_row = rows["small_prescribed_motion"]
    construct = rows["function_object_construction"]
    passed = (
        clean["build_d_sha256"] == EXPECTED_LIBRARY_SHA256
        and clean["build_e_sha256"] == EXPECTED_LIBRARY_SHA256
        and clean["byte_identical"]
        and zero["completed"] and zero["ordinary_cell_displacement_solve_observed"]
        and small_row["completed"] and small_row["force_decomposition_observed"]
        and small_row["point_displacement_written"] and small_row["mesh_points_written"]
        and ab_pass
        and construct["adapter_banner_observed"] and construct["read_precice_dict_observed"]
        and construct["expected_negative_config"] and construct["no_participant_initialized"]
    )
    payload = {"schema_version": "reproducible-openfoam10-adapter-baseline-recovery-v1", "NONCOUPLED_REGRESSION": "PASS" if passed else "FAIL", **rows}
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"NONCOUPLED_REGRESSION": payload["NONCOUPLED_REGRESSION"]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
