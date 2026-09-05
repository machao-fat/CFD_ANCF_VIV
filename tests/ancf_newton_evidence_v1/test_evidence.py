from __future__ import annotations

import copy
import unittest

from coupling.ancf_newton_evidence_v1 import NewtonEvidenceError, make_record, validate_records


def record(step: int, phase: str) -> dict[str, object]:
    sequence = 2 * step - 1 if phase == "prediction" else 2 * step
    return make_record(
        run_id="fresh-run", case_id="fresh-case", global_step=step,
        time_s=0.005 * step, integer_tick=5_000_000 * step, phase=phase,
        transport_sequence=sequence,
        correction_sequence=sequence if phase == "correction" else None,
        diagnostics={"newton_iterations": 2, "newton_final_residual": 1e-12,
                     "newton_converged": True, "finite_value_audit": True,
                     "worker_return_code": 0},
        state={"q": [1.0, 2.0], "qdot": [3.0, 4.0], "qddot": [5.0, 6.0]},
        max_newton_iterations=40,
    )


class NewtonEvidenceTests(unittest.TestCase):
    def test_two_steps_are_complete_and_identity_continuous(self):
        records = [record(step, phase) for step in (1, 2) for phase in ("prediction", "correction")]
        result = validate_records(records, expected_steps=2)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["record_count"], 4)
        self.assertEqual(result["prediction_count"], 2)
        self.assertEqual(result["correction_count"], 2)

    def test_missing_wire_diagnostic_fails_closed(self):
        with self.assertRaises(NewtonEvidenceError):
            make_record(
                run_id="run", case_id="case", global_step=1, time_s=.005,
                integer_tick=5_000_000, phase="prediction", transport_sequence=1,
                correction_sequence=None,
                diagnostics={"newton_iterations": 1, "newton_converged": True,
                             "finite_value_audit": True, "worker_return_code": 0},
                state={"q": [0.0], "qdot": [0.0], "qddot": [0.0]},
                max_newton_iterations=40,
            )

    def test_duplicate_or_mutated_state_fails_closed(self):
        records = [record(1, "prediction"), record(1, "correction")]
        duplicate = records + [copy.deepcopy(records[1]), record(2, "prediction")]
        with self.assertRaises(NewtonEvidenceError):
            validate_records(duplicate, expected_steps=2)
        corrupted = copy.deepcopy(records)
        corrupted[1]["state"]["q"][0] = 99.0  # type: ignore[index]
        with self.assertRaises(NewtonEvidenceError):
            validate_records(corrupted, expected_steps=1)

    def test_time_tick_mismatch_fails_closed(self):
        with self.assertRaises(NewtonEvidenceError):
            make_record(
                run_id="run", case_id="case", global_step=1, time_s=.005,
                integer_tick=5_000_001, phase="prediction", transport_sequence=1,
                correction_sequence=None,
                diagnostics={"newton_iterations": 1, "newton_final_residual": 0.0,
                             "newton_converged": True, "finite_value_audit": True,
                             "worker_return_code": 0},
                state={"q": [0.0], "qdot": [0.0], "qddot": [0.0]},
                max_newton_iterations=40,
            )


if __name__ == "__main__":
    unittest.main()
