"""Run one explicitly authorized fresh three-slice segment from C++ t=0.

This entry point is deliberately bounded to 40 steps (0.05 s).  It binds the
audited C++ static-equilibrium state and the fresh three-slice templates; it
does not reuse any Stage 233/old continuation checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm
from coupling.cpp_worker_confirm_v1.cpp_adapter import _model_contract_sha256
from coupling.cpp_worker_confirm_v1.coordinator import _fixture as _base_fixture
from coupling.cpp_worker_confirm_v1.numerical_contract import normalize_model


STAGE_ID = "stage4f_d_cpp_worker_fresh_t0_v1"
RUN_ID = "cpp_worker_fresh_t0_real_001"
CASE_ID = "cpp_worker_fresh_t0_real_case_001"
SOURCE = PROJECT / "runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only/ancf_t0_state_cpp.json"
SOURCE_SHA256 = "d4c8d0a63c95f07c53d8f4dd2bda2f60c2625ab70f52598cf97bd60404caca7f"
TEMPLATE_ROOT = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v2/run_20260827_retry1/cases"
WORKER_EXE = PROJECT / "runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only/cfd_ancf_ancf_kernel_worker.exe"
LIBRARY = PROJECT / "runtime/cpp_worker_to70s_build_retry_v11/lib/libancfFileMotion.so"
EXPECTED_LIBRARY_SHA256 = "39a51c9a01da1ed63a761b4385d8eb954dc201415f7e21aa3ca9f1cb7087bd07"
RUNTIME = PROJECT / "runtime/cpp_worker_fresh_t0_v1/real_run_001"
RESULTS = PROJECT / "results/240_cpp_worker_fresh_t0_real_v1"
DOCS = PROJECT / "docs/240_cpp_worker_fresh_t0_real_v1"
PREFLIGHT_AUDIT = PROJECT / "results/239_cpp_worker_fresh_t0_real_preflight_v1/fresh_t0_real_launch_preflight.json"
SOURCE_GLOBAL_STEP = 0
SOURCE_TIME_S = 0.0
SOURCE_TICK = 0
AUTHORIZED_STEPS = 40
TARGET_FINAL_STEP = 40
TARGET_FINAL_TIME_S = 0.05
TARGET_FINAL_TICK = 50_000_000
GATE_ID = "STAGE4F_D_CPP_WORKER_FRESH_T0_REAL_V1_GATE"
GATE_FILENAME = "stage4f_d_cpp_worker_fresh_t0_real_v1_gate.json"
SPARSE_RETENTION = False
SPARSE_KEEP_FULL_STEPS = 40

confirm.STAGE_ID = STAGE_ID
confirm.RUN_ID = RUN_ID
confirm.CASE_ID = CASE_ID
confirm.SOURCE = SOURCE
confirm.SOURCE_SHA256 = SOURCE_SHA256
confirm.MASS_MATRIX_SOURCE = SOURCE
confirm.LIBRARY = LIBRARY
confirm.EXPECTED_LIBRARY_SHA256 = EXPECTED_LIBRARY_SHA256
confirm.WORKER_EXE = WORKER_EXE
confirm.TEMPLATE_ROOT = TEMPLATE_ROOT
confirm.SOURCE_GLOBAL_STEP = SOURCE_GLOBAL_STEP
confirm.SOURCE_TIME_S = SOURCE_TIME_S
confirm.SOURCE_TICK = SOURCE_TICK
confirm.AUTHORIZED_STEPS = AUTHORIZED_STEPS
confirm.TARGET_FINAL_STEP = TARGET_FINAL_STEP
confirm.TARGET_FINAL_TIME_S = TARGET_FINAL_TIME_S
confirm.TARGET_FINAL_TICK = TARGET_FINAL_TICK
confirm.RUNTIME = RUNTIME
confirm.RESULTS = RESULTS
confirm.DOCS = DOCS
confirm.GATE_ID = GATE_ID
confirm.GATE_FILENAME = GATE_FILENAME
confirm.SPARSE_RETENTION = SPARSE_RETENTION
confirm.SPARSE_KEEP_FULL_STEPS = SPARSE_KEEP_FULL_STEPS
confirm.os.environ["CFD_ANCF_VIV_CPP_FIXTURE"] = str(
    PROJECT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
)


def _state() -> dict[str, object]:
    return json.loads(SOURCE.read_bytes().decode("utf-8"))


def _source_mass_matrix() -> tuple[float, ...]:
    state = _state()
    values = tuple(float(value) for value in state.get("mass_matrix", []))
    if len(values) != 102 * 102 or any(not math.isfinite(value) for value in values):
        raise RuntimeError("fresh t=0 source mass matrix is not finite 102x102")
    return values


def _restart_payload_from_source(source: dict[str, object]):
    structure = {key: source[key] for key in ("q", "qdot", "qddot")}
    # At t=0 no previous hydrodynamic load exists.  The first correction is
    # therefore seeded only with the audited static-equilibrium state.
    return {"structure": structure}, [[0.0, 0.0, 0.0] for _ in range(3)]


def _fresh_fixture():
    model, _q, _qdot, _qddot, _base_load = _base_fixture()
    state = _state()
    return (model, tuple(float(value) for value in state["q"]),
            tuple(float(value) for value in state["qdot"]),
            tuple(float(value) for value in state["qddot"]),
            tuple(float(value) for value in state["base_load"]))


def _validate_scope(contract, manifest) -> None:
    contract.validate(PROJECT)
    if manifest.case_id != CASE_ID or len(manifest.slices) != 3:
        raise RuntimeError("fresh t=0 manifest identity/slice scope mismatch")
    state = _state()
    if (state.get("state_kind") != "cpp_reference_state" or
            state.get("schema_version") != "ancf-t0-cpp-v2" or
            state.get("global_step") != 0 or state.get("time_s") != 0.0 or
            state.get("integer_tick") != 0 or state.get("equilibrated") is not True or
            state.get("finite_value_audit") is not True):
        raise RuntimeError("fresh source is not the audited C++ static-equilibrium state")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("fresh source SHA-256 mismatch")
    if not WORKER_EXE.is_file() or not TEMPLATE_ROOT.is_dir() or not LIBRARY.is_file():
        raise RuntimeError("fresh C++ worker, library, or slice templates are missing")
    if confirm._sha256(LIBRARY) != EXPECTED_LIBRARY_SHA256:
        raise RuntimeError("fresh ancfFileMotion library hash mismatch")
    for sid in range(3):
        root = TEMPLATE_ROOT / f"slice_{sid:04d}"
        if not root.is_dir() or not all((root / "0" / name).is_file()
                                         for name in ("U", "p", "phi", "Uf", "meshPhi", "motionScale")):
            raise RuntimeError(f"fresh slice {sid} template is incomplete")


model, *_ = _base_fixture()
model = normalize_model(model)
EXPECTED_MODEL_CONTRACT_SHA256 = _model_contract_sha256(model, _source_mass_matrix())
if EXPECTED_MODEL_CONTRACT_SHA256 is None:
    raise RuntimeError("fresh model contract hash cannot be serialized")
confirm.EXPECTED_MODEL_CONTRACT_SHA256 = EXPECTED_MODEL_CONTRACT_SHA256
confirm._source_mass_matrix = _source_mass_matrix
confirm._restart_payload_from_source = _restart_payload_from_source
confirm._fixture = _fresh_fixture
confirm._validate_scope = _validate_scope


def _require_preflight() -> None:
    audit_path = PREFLIGHT_AUDIT
    if not audit_path.is_file():
        raise RuntimeError("fresh t=0 preflight is missing; run prepare_fresh_t0_real_launch_v1.py first")
    audit = json.loads(audit_path.read_bytes().decode("utf-8"))
    expected_gate = "STAGE4F_D_CPP_WORKER_FRESH_T0_REAL_PREFLIGHT_V1_GATE: pass"
    if audit.get("gate") != expected_gate or audit.get("launch_performed") is not False:
        raise RuntimeError("fresh t=0 preflight did not pass fail-closed")
    if (audit.get("case_id") != CASE_ID or
            audit.get("source", {}).get("sha256") != SOURCE_SHA256 or
            not all(audit.get("checks", {}).values())):
        raise RuntimeError("fresh t=0 preflight identity or checks do not match this launcher")
    if any(value != 0 for value in audit.get("real_process_starts", {}).values()):
        raise RuntimeError("preflight contains unexpected real process starts")


def main() -> int:
    if sys.argv[1:] != ["--authorize-real"]:
        print("refusing to start: pass --authorize-real only after a new explicit real-CFD authorization", file=sys.stderr)
        return 2
    _require_preflight()
    return confirm.main()


if __name__ == "__main__":
    raise SystemExit(main())
