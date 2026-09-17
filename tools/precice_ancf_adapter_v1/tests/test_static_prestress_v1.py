import json
from pathlib import Path
import tempfile
import unittest

from tools.precice_ancf_adapter_v1.ancf_case_config_v1 import CaseConfig, CaseConfigError
from tools.precice_ancf_adapter_v1.ancf_generic_participant_v1 import GenericANCFParticipant
from tools.precice_ancf_adapter_v1.ancf_static_prestress_v1 import (
    PrestressError,
    RESULT_SCHEMA_VERSION,
    StaticPrestressInitializer,
    make_synthetic_case,
    read_result_file,
)


def fake_solver(request_text):
    tokens = request_text.split()
    delta = float(tokens[22])
    top = 100000.0 * delta
    q = [0.0] * 102
    return {
        "status": "PASS",
        "top_tension_N": top,
        "top_reaction": [0.0, 0.0, top],
        "bottom_reaction": [0.0, 0.0, -top],
        "external_total": [0.0, 0.0, 0.0],
        "global_balance_error": 0.0,
        "max_abs_lambda_minus_1": 0.0,
        "iterations": 1,
        "non_descent_failures": 0,
        "line_search_failures": 0,
        "minimum_accepted_beta": 1.0,
        "maximum_backtrack_depth": 0,
        "unchanged_trials_seen": 0,
        "unchanged_trials_accepted": 0,
        "base_load": [0.0] * 102,
        "q": q,
        "qdot": q,
        "qddot": q,
    }


class StaticPrestressUnitTests(unittest.TestCase):
    def test_case_config_strategy_and_boundary(self):
        config = CaseConfig.from_mapping(make_synthetic_case())
        spec = config.prestress_spec()
        self.assertEqual(spec["mode"], "installed_stretch_target_top_reaction")
        self.assertEqual(spec["installation_axis"], (0.0, 0.0, 1.0))
        self.assertEqual(spec["bottom_position_m"], (0.0, 0.0, 0.0))
        self.assertEqual(config.boundary_arrays()[0], (0, 1, 2, 96, 97, 98))

    def test_positive_submerged_weight(self):
        config = CaseConfig.from_mapping(make_synthetic_case())
        initializer = StaticPrestressInitializer(config, "unused", runner=fake_solver)
        self.assertGreater(initializer.omega_s, 0.0)

    def test_deterministic_bisection(self):
        config = CaseConfig.from_mapping(make_synthetic_case())
        result = StaticPrestressInitializer(config, "unused", runner=fake_solver).calibrate()
        self.assertTrue(result["bracket_valid"])
        self.assertLessEqual(abs(result["final"]["top_tension_N"] - 5000.0) / 5000.0, 1.0e-6)
        self.assertGreaterEqual(len(result["history"]), 3)

    def test_incompatible_boundary_rejected(self):
        raw = make_synthetic_case()
        raw["boundary"] = {
            "contract_id": "gradient_clamped",
            "fixed_dof": [0, 1, 2, 102, 103, 104, 107],
            "prescribed_values": [0.0] * 7,
        }
        config = CaseConfig.from_mapping(raw)
        with self.assertRaises(CaseConfigError):
            config.prestress_spec()

    def test_invalid_mode_and_target_rejected(self):
        raw = make_synthetic_case()
        raw["prestress"]["mode"] = "other"
        with self.assertRaises(CaseConfigError):
            CaseConfig.from_mapping(raw)
        raw = make_synthetic_case()
        raw["prestress"]["target_reaction_N"] = 0.0
        with self.assertRaises(CaseConfigError):
            CaseConfig.from_mapping(raw)

    def test_static_artifact_and_prestressed_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = make_synthetic_case()
            config = CaseConfig.from_mapping(raw, base_dir=root)
            initializer = StaticPrestressInitializer(config, "unused", runner=fake_solver)
            calibration = initializer.calibrate()
            artifact = initializer.make_static_artifact(
                calibration,
                "protocol-sha-placeholder",
                "commit-placeholder",
            )
            path = root / raw["initial_state"]["state_file"]
            path.write_text(json.dumps(artifact), encoding="utf-8")
            state = config.initial_state()
            self.assertEqual(state["time_s"], 0.0)
            self.assertEqual(state["global_step"], 0)
            self.assertTrue(all(value == 0.0 for value in state["qdot"]))
            participant = GenericANCFParticipant(
                config,
                [type("Backend", (), {})()],
                lambda request: {"q": request.q, "qdot": request.qdot, "qddot": request.qddot},
            )
            self.assertEqual(tuple(participant.q), tuple(artifact["q"]))
            self.assertEqual(tuple(participant.model.prescribed_values),
                             tuple(artifact["boundary"]["prescribed_values"]))

    def test_model_static_does_not_accept_caller_vector(self):
        raw = make_synthetic_case()
        raw["base_load"]["vector"] = [0.0] * 102
        config = CaseConfig.from_mapping(raw)
        self.assertEqual(config.base_load_vector(), (0.0,) * 102)

    def test_nonconservative_damping_remains_rejected(self):
        raw = make_synthetic_case()
        raw["numerics"]["damping_alpha"] = 0.01
        with self.assertRaises(CaseConfigError):
            CaseConfig.from_mapping(raw)

    def test_result_file_valid_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps({
                "schema_version": RESULT_SCHEMA_VERSION,
                "evaluation_id": "unit-01",
                "status": "PASS",
                "static_status": "CONVERGED",
                "DeltaL_m": 0.0, "H_m": 1.0, "top_tension_N": 1.0,
                "top_reaction_vector_N": [0.0, 0.0, 1.0],
                "bottom_reaction_vector_N": [0.0, 0.0, -1.0],
                "global_balance_error": 0.0, "q": [0.0],
                "potential_diagnostics": {"iterations": 0},
            }), encoding="utf-8")
            self.assertEqual(read_result_file(path, "unit-01")["evaluation_id"], "unit-01")

    def test_result_file_rejects_nonfinite_and_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text('{"schema_version":"ANCF_STATIC_PRESTRESS_RESULT_V1.2",'
                            '"evaluation_id":"unit-02","status":"PASS",'
                            '"value":NaN}', encoding="utf-8")
            with self.assertRaises(PrestressError):
                read_result_file(path, "unit-02")
            path.write_text(json.dumps({
                "schema_version": RESULT_SCHEMA_VERSION,
                "evaluation_id": "old-id", "status": "FAIL",
                "failure_classification": "X",
            }), encoding="utf-8")
            with self.assertRaises(PrestressError):
                read_result_file(path, "unit-02")

    def test_result_file_rejects_missing_and_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            with self.assertRaises(PrestressError):
                read_result_file(path, "unit-03")
            path.with_name(path.name + ".tmp.unit-03").write_text("{", encoding="utf-8")
            with self.assertRaises(PrestressError):
                read_result_file(path, "unit-03")


if __name__ == "__main__":
    unittest.main()
