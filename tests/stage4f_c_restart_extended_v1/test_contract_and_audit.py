from __future__ import annotations

import copy
import hashlib
import json
import unittest

from src.coupling.stage4f_c_restart_extended_v1.audit import (
    RestartExtendedAuditError,
    audit_restart_identity,
    authorize_extended_transient,
)
from src.coupling.stage4f_c_restart_extended_v1.contract import (
    CFD_FIELDS,
    END_TIME_S,
    EXTENSION_STEPS,
    FINAL_MAX_ABS_CD,
    MAX_ITERATIONS_PER_STEP,
    RELAXATION_ALPHA,
    TOTAL_AUTHORIZED_STEPS,
    build_contract,
    validate_contract,
)


ORIGINAL = "a" * 64


def _rehash(value):
    payload = dict(value)
    payload.pop("contract_sha256", None)
    value["contract_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _fields(step, *, parsed=False):
    output = {}
    for index, field in enumerate(CFD_FIELDS):
        entry = {"sha256": f"{step + index + 1:064x}"}
        if parsed:
            entry["sha256"] = f"{step + index + 101:064x}"
            entry["parsed_values"] = [[float(step), float(index)], [0.0]]
        output[field] = entry
    return output


def _step(step, parent, current, *, parsed=False):
    return {
        "physical_step": step,
        "predictor": {
            "q": [1.0 + step, 2.0],
            "qdot": [3.0, 4.0 + step],
            "qddot": [[5.0], [6.0 + step]],
        },
        "cfd_fields": _fields(step, parsed=parsed),
        "observed_forces_N": [[10.0 + step, 0.0, 0.0], [0.0, 20.0 + step, 0.0], [0.0, 0.0, 30.0 + step]],
        "checkpoint": {"parent_checkpoint_sha256": parent, "checkpoint_sha256": current},
    }


def _evidence(*, parsed=False):
    c0, c1, c2 = "b" * 64, "c" * 64, "d" * 64
    r0, r1, r2 = "e" * 64, "f" * 64, "0" * 64
    continuous = [_step(0, ORIGINAL, c0, parsed=parsed), _step(1, c0, c1, parsed=parsed), _step(2, c1, c2, parsed=parsed)]
    first_leg = [_step(0, ORIGINAL, r0, parsed=parsed)]
    restart = [_step(1, r0, r1, parsed=parsed), _step(2, r1, r2, parsed=parsed)]
    if parsed:
        for left, right in zip(continuous, first_leg + restart):
            right["cfd_fields"] = copy.deepcopy(left["cfd_fields"])
            for field in CFD_FIELDS:
                right["cfd_fields"][field]["sha256"] = "1" * 64
    shutdown = {
        "phase": "after_first_leg_before_restart", "source_checkpoint_sha256": r0,
        "owned_processes_started": 5, "owned_processes_closed": 5,
        "owned_processes_residual": 0, "nonzero_return_codes": 0,
    }
    return continuous, first_leg, restart, shutdown


class RestartExtendedContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = build_contract(ORIGINAL)

    def test_frozen_contract_preserves_the_requested_limits_and_scope(self):
        validate_contract(self.contract)
        self.assertEqual(self.contract["execution_mode"], "real_restart_identity_then_bounded_extension")
        self.assertEqual(self.contract["relaxation_alpha"], RELAXATION_ALPHA)
        self.assertEqual(self.contract["max_iterations_per_physical_step"], MAX_ITERATIONS_PER_STEP)
        self.assertEqual(self.contract["final_max_abs_Cd"], FINAL_MAX_ABS_CD)
        self.assertEqual(self.contract["max_CFL_exclusive"], 0.8)
        self.assertEqual(self.contract["consecutive_residual_converged_iterations"], 2)
        self.assertEqual(self.contract["additional_authorized_physical_steps"], EXTENSION_STEPS)
        self.assertEqual(self.contract["total_authorized_physical_steps"], TOTAL_AUTHORIZED_STEPS)
        self.assertEqual(self.contract["authorized_end_time_s"], END_TIME_S)

    def test_rehashed_contract_tampering_is_rejected(self):
        tampered = build_contract(ORIGINAL)
        tampered["additional_authorized_physical_steps"] = 8
        _rehash(tampered)
        with self.assertRaisesRegex(ValueError, "frozen"):
            validate_contract(tampered)


class RestartIdentityAuditTests(unittest.TestCase):
    def setUp(self):
        self.contract = build_contract(ORIGINAL)

    def _audit(self, *, parsed=False):
        continuous, first_leg, restart, shutdown = _evidence(parsed=parsed)
        return audit_restart_identity(
            self.contract, continuous_steps=continuous, first_leg_steps=first_leg,
            restart_leg_steps=restart, shutdown_audit=shutdown,
        )

    def test_exact_hash_identity_passes_and_authorizes_exactly_seven_steps(self):
        audit = self._audit()
        authorization = authorize_extended_transient(self.contract, audit)
        self.assertEqual(audit["status"], "passed")
        self.assertEqual(authorization["additional_physical_steps"], 7)
        self.assertEqual(authorization["total_physical_steps"], 10)
        self.assertEqual(authorization["end_time_s"], 1.51375)

    def test_strict_parsed_numeric_cfd_identity_is_an_accepted_hash_alternative(self):
        audit = self._audit(parsed=True)
        self.assertEqual(audit["steps"][1]["cfd_comparison"]["U"], "parsed_values")

    def test_structure_relative_difference_above_1e_minus_11_is_rejected(self):
        continuous, first_leg, restart, shutdown = _evidence()
        restart[1]["predictor"]["q"][0] += 4.0e-11
        with self.assertRaisesRegex(RestartExtendedAuditError, "relative difference"):
            audit_restart_identity(self.contract, continuous_steps=continuous, first_leg_steps=first_leg, restart_leg_steps=restart, shutdown_audit=shutdown)

    def test_cfd_hash_mismatch_without_identical_parsed_values_is_rejected(self):
        continuous, first_leg, restart, shutdown = _evidence()
        restart[0]["cfd_fields"]["U"]["sha256"] = "1" * 64
        with self.assertRaisesRegex(RestartExtendedAuditError, "no identical hash"):
            audit_restart_identity(self.contract, continuous_steps=continuous, first_leg_steps=first_leg, restart_leg_steps=restart, shutdown_audit=shutdown)

    def test_parsed_cfd_value_mismatch_is_rejected_even_when_it_is_finite(self):
        continuous, first_leg, restart, shutdown = _evidence(parsed=True)
        restart[1]["cfd_fields"]["meshPhi"]["parsed_values"][0][0] = 99.0
        with self.assertRaisesRegex(RestartExtendedAuditError, "parsed values differ"):
            audit_restart_identity(self.contract, continuous_steps=continuous, first_leg_steps=first_leg, restart_leg_steps=restart, shutdown_audit=shutdown)

    def test_observed_force_mismatch_is_rejected(self):
        continuous, first_leg, restart, shutdown = _evidence()
        restart[1]["observed_forces_N"][0][0] += 1.0e-14
        with self.assertRaisesRegex(RestartExtendedAuditError, "observed CFD forces differ"):
            audit_restart_identity(self.contract, continuous_steps=continuous, first_leg_steps=first_leg, restart_leg_steps=restart, shutdown_audit=shutdown)

    def test_restart_lineage_must_begin_at_the_committed_first_leg_checkpoint(self):
        continuous, first_leg, restart, shutdown = _evidence()
        restart[0]["checkpoint"]["parent_checkpoint_sha256"] = "1" * 64
        with self.assertRaisesRegex(RestartExtendedAuditError, "restart_leg\[0\] checkpoint lineage"):
            audit_restart_identity(self.contract, continuous_steps=continuous, first_leg_steps=first_leg, restart_leg_steps=restart, shutdown_audit=shutdown)

    def test_restart_is_rejected_until_all_owned_processes_are_closed(self):
        continuous, first_leg, restart, shutdown = _evidence()
        shutdown["owned_processes_residual"] = 1
        with self.assertRaisesRegex(RestartExtendedAuditError, "residual processes"):
            audit_restart_identity(self.contract, continuous_steps=continuous, first_leg_steps=first_leg, restart_leg_steps=restart, shutdown_audit=shutdown)

    def test_extension_requires_a_passing_audit_for_the_same_contract(self):
        audit = self._audit()
        audit["contract_sha256"] = "0" * 64
        with self.assertRaisesRegex(RestartExtendedAuditError, "not authorized"):
            authorize_extended_transient(self.contract, audit)


if __name__ == "__main__":
    unittest.main()
