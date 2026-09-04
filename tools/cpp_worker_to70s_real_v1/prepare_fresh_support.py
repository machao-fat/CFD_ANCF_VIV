"""Materialize fresh C++ support inputs from immutable accepted artifacts.

This utility writes only the new Stage 233 runtime support directory.  It
never starts a solver and never modifies the source checkpoint or MATLAB
artifact.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from scipy.io import loadmat

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
MASS_SOURCE = PROJECT / "cases/openfoam/stage4f_c_case_initialization_repair_v1/C/matlab/committed.mat"
SUPPORT = PROJECT / "runtime/cpp_worker_to70s_real_v1/run_001/support"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def main() -> int:
    if SUPPORT.exists() and any(SUPPORT.iterdir()):
        raise RuntimeError(f"fresh support destination is not empty: {SUPPORT}")
    source = json.loads(SOURCE.read_bytes().decode("utf-8"))
    structure = source["structure"]
    mat = loadmat(MASS_SOURCE, squeeze_me=True, struct_as_record=False)
    state = mat["state"]
    model = state.model
    required = {
        "length_m": float(model.geometry.L), "diameter_m": float(model.geometry.D),
        "inner_diameter_m": float(model.geometry.d), "elements": int(model.geometry.n_elem),
        "slices": 3, "top_tension_N": float(model.boundary.top_tension_N),
        "youngs_modulus_Pa": float(model.material.E), "material_density": float(model.material.rho),
        "fluid_density": float(model.fluid.rho), "gravity": float(model.fluid.g),
        "beta": float(model.time.beta), "gamma": float(model.time.gamma),
        "newton_tolerance": float(model.time.newton_tolerance),
        "damping_alpha": float(model.damping.rayleigh_alpha),
        "damping_beta": float(model.damping.rayleigh_beta),
        "gauss_order": 3, "max_newton": 40,
        "slice_positions_m": [float(v) for v in model.coupling.s_ref_m],
        "q": [float(v) for v in structure["q"]],
        "qdot": [float(v) for v in structure["qdot"]],
        "qddot": [float(v) for v in structure["qddot"]],
        "base_load": [float(v) for v in state.base_load.reshape(-1)],
    }
    if len(required["q"]) != 102 or len(required["qdot"]) != 102 or len(required["qddot"]) != 102:
        raise RuntimeError("source state dimension is not 102")
    SUPPORT.mkdir(parents=True, exist_ok=False)
    (SUPPORT / "cpp_input_fixture.json").write_bytes(canonical(required))
    shutil.copy2(MASS_SOURCE, SUPPORT / "committed.mat")
    audit = {
        "stage_id": "stage4f_d_cpp_worker_to70s_real_v1",
        "source_checkpoint": str(SOURCE), "source_checkpoint_sha256": sha256(SOURCE),
        "mass_matrix_source": str(MASS_SOURCE), "mass_matrix_source_sha256": sha256(MASS_SOURCE),
        "fixture": str(SUPPORT / "cpp_input_fixture.json"),
        "fixture_sha256": sha256(SUPPORT / "cpp_input_fixture.json"),
        "fixture_schema": "cpp_worker_kernel_fixture_v1",
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "old_artifacts_modified": False,
    }
    (SUPPORT / "support_audit.json").write_bytes(canonical(audit))
    print(json.dumps(audit, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
