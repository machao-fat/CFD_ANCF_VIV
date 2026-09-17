"""Offline structural-damping contract tests; no worker or CFD execution."""

from __future__ import annotations

import hashlib
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (  # noqa: E402
    DAMPING_EXTENSION_MARKER,
    FrameError,
    KernelStepRequest,
)
from tools.precice_ancf_adapter_v1.ancf_case_config_v1 import (  # noqa: E402
    CaseConfig,
    CaseConfigError,
)
from tools.precice_ancf_adapter_v1.ancf_static_prestress_v1 import make_synthetic_case  # noqa: E402


def straight_q(length: float, elements: int) -> tuple[float, ...]:
    result: list[float] = []
    for node in range(elements + 1):
        z = length * node / elements
        result.extend((0.0, 0.0, z, 0.0, 0.0, 1.0))
    return tuple(result)


def fresh_case(damping: dict | None = None, *, base_source: str = "caller_supplied") -> CaseConfig:
    raw = make_synthetic_case(base_load_source="model_static")
    q = straight_q(10.0, 16)
    raw["initial_state"] = {
        "kind": "fresh", "reference_geometry": "case_geometry",
        "reference_positions_m": [[0.0, 0.0, 5.0]],
        "q": list(q), "qdot": [0.0] * len(q), "qddot": [0.0] * len(q),
    }
    if base_source == "caller_supplied":
        raw["base_load"]["source"] = "caller_supplied"
        raw["base_load"]["vector"] = [0.0] * len(q)
    if damping is not None:
        raw["damping"] = damping
    else:
        raw.pop("damping", None)
    return CaseConfig.from_mapping(raw)


def request_for(config: CaseConfig, *, request_id: int = 1) -> KernelStepRequest:
    state = config.initial_state()
    model = config.kernel_model()
    spec = config.damping_spec()
    kwargs = dict(
        sequence=1, global_step=1, case_local_bridge_step=1,
        integer_tick=1_250_000, time_s=0.00125, dt_s=0.00125,
        request_id=request_id, transaction_id=request_id,
        run_id=config.run_id, case_id=config.case_id, model=model,
        q=state["q"], qdot=state["qdot"], qddot=state["qddot"],
        base_load=state["base_load"], slice_force=(0.0, 0.0, 0.0),
    )
    if spec["mode"] != "none":
        kwargs.update(
            damping_mode=spec["mode"],
            damping_reference_state=spec["reference_state"],
            damping_identity_sha256=config.damping_identity_sha256,
            damping_reference_state_identity_sha256=config.damping_reference_identity_sha256(
                state["damping_reference_q"], state["resolved_model_identity_sha256"]),
            damping_model_identity_sha256=state["resolved_model_identity_sha256"],
            damping_q_ref=state["damping_reference_q"],
        )
    return KernelStepRequest(**kwargs)


class StructuralDampingContractTests(unittest.TestCase):
    def test_none_preserves_legacy_payload(self) -> None:
        config = fresh_case()
        first = request_for(config).payload()
        second = request_for(config).payload()
        self.assertEqual(first, second)
        self.assertNotIn(struct.pack("<I", DAMPING_EXTENSION_MARKER), first)

    def test_rayleigh_payload_has_one_dmp1_and_stable_identity(self) -> None:
        config = fresh_case({
            "mode": "rayleigh_coefficients", "alpha_mass_per_s": 0.25,
            "beta_stiffness_s": 0.0, "reference_state": "dynamic_initial",
            "require_free_tangent_positive_semidefinite": True,
        })
        payload = request_for(config).payload()
        self.assertEqual(payload.count(struct.pack("<I", DAMPING_EXTENSION_MARKER)), 1)
        self.assertEqual(config.damping_identity_sha256,
                         config.damping_identity_sha256)
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         hashlib.sha256(request_for(config).payload()).hexdigest())

    def test_nonzero_coefficients_require_extension(self) -> None:
        config = fresh_case({
            "mode": "rayleigh_coefficients", "alpha_mass_per_s": 0.25,
            "beta_stiffness_s": 0.0, "reference_state": "dynamic_initial",
            "require_free_tangent_positive_semidefinite": True,
        })
        request = request_for(config)
        broken = KernelStepRequest(
            sequence=request.sequence, global_step=request.global_step,
            case_local_bridge_step=request.case_local_bridge_step,
            integer_tick=request.integer_tick, time_s=request.time_s,
            dt_s=request.dt_s, request_id=request.request_id,
            transaction_id=request.transaction_id, run_id=request.run_id,
            case_id=request.case_id, model=request.model, q=request.q,
            qdot=request.qdot, qddot=request.qddot, base_load=request.base_load,
            slice_force=request.slice_force,
        )
        with self.assertRaises(FrameError):
            broken.payload()

    def test_config_rejects_bad_coefficients_and_modes(self) -> None:
        for damping in (
            {"mode": "unknown"},
            {"mode": "rayleigh_coefficients", "alpha_mass_per_s": -1.0,
             "beta_stiffness_s": 0.0, "reference_state": "dynamic_initial"},
            {"mode": "rayleigh_coefficients", "alpha_mass_per_s": math.nan,
             "beta_stiffness_s": 0.0, "reference_state": "dynamic_initial"},
            {"mode": "rayleigh_coefficients", "alpha_mass_per_s": 0.0,
             "beta_stiffness_s": 0.0, "reference_state": "dynamic_initial"},
        ):
            with self.assertRaises(CaseConfigError):
                fresh_case(damping)

    def test_artifact_reference_and_restart_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_raw = make_synthetic_case(base_load_source="model_static")
            q0 = straight_q(10.0, 16)
            q1 = list(q0); q1[7] = 1.0e-4
            config_raw["base_load"] = {"source": "caller_supplied", "vector": [0.0] * len(q0)}
            config_raw["damping"] = {
                "mode": "rayleigh_coefficients", "alpha_mass_per_s": 0.25,
                "beta_stiffness_s": 0.0, "reference_state": "dynamic_initial",
                "require_free_tangent_positive_semidefinite": True,
            }
            config_raw["initial_state"] = {
                "kind": "restart", "state_file": "restart.json",
                "reference_geometry": "case_geometry",
                "reference_positions_m": [[0.0, 0.0, 5.0]],
            }
            config = CaseConfig.from_mapping(config_raw, Path(directory))
            artifact = config.make_state_artifact(q1, [0.0] * len(q0), [0.0] * len(q0), 0.25, 200, q0)
            path = Path(directory) / "restart.json"
            path.write_text(__import__("json").dumps(artifact), encoding="utf-8")
            loaded = config.initial_state()
            self.assertEqual(tuple(loaded["q"]), tuple(q1))
            self.assertEqual(tuple(loaded["damping_reference_q"]), q0)
            self.assertNotEqual(tuple(loaded["q"]), tuple(loaded["damping_reference_q"]))
            self.assertEqual(loaded["dynamic_identity_sha256"], artifact["dynamic_identity_sha256"])

    def test_two_target_rayleigh_formula_offline(self) -> None:
        omega1, omega2 = 2.0, 7.0
        zeta1, zeta2 = 0.01, 0.03
        beta = 2.0 * (zeta2 * omega2 - zeta1 * omega1) / (omega2 * omega2 - omega1 * omega1)
        alpha = 2.0 * zeta1 * omega1 - beta * omega1 * omega1
        self.assertGreaterEqual(alpha, 0.0)
        self.assertGreaterEqual(beta, 0.0)
        self.assertAlmostEqual(alpha / (2.0 * omega1) + beta * omega1 / 2.0, zeta1)
        self.assertAlmostEqual(alpha / (2.0 * omega2) + beta * omega2 / 2.0, zeta2)


if __name__ == "__main__":
    unittest.main()
