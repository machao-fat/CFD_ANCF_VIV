import json
import unittest

from tools.precice_ancf_adapter_v1.run_static_prestress_regression_v1_3 import (
    _summary_states,
)


def _record(evaluation_id, delta_length_m, top_tension_N):
    return {
        "evaluation_id": evaluation_id,
        "DeltaL_m": delta_length_m,
        "H_m": 10.0 + delta_length_m,
        "top_tension_N": top_tension_N,
        "status": "PASS",
        "static_status": "CONVERGED",
    }


class StaticPrestressSummaryCorrectionTests(unittest.TestCase):
    def _calibration(self):
        target = 5000.0
        low = _record("eval-000001", 0.0087670037828830698, 1283.4131085849642)
        high = _record("eval-000002", 0.070136030263064558, 10062.180740860984)
        final_low = _record("eval-000021", 0.0348851964281512,
                            target - 0.007842792067094706)
        final_high = _record("eval-000020", 0.034885313480279956,
                             target + 0.008878544525941834)
        accepted = _record("eval-000022", 0.034885254954215579,
                           5000.0005178807523)
        return {
            "initial_low_result": low,
            "initial_high_result": high,
            "initial_low_f_N": low["top_tension_N"] - target,
            "initial_high_f_N": high["top_tension_N"] - target,
            "final_bracket_low_result": final_low,
            "final_bracket_high_result": final_high,
            "final_bracket_low_f_N": final_low["top_tension_N"] - target,
            "final_bracket_high_f_N": final_high["top_tension_N"] - target,
            "accepted_result": accepted,
            "accepted_f_N": accepted["top_tension_N"] - target,
        }

    def test_three_named_states_keep_whole_evaluation_tuples(self):
        summary = _summary_states(self._calibration(), 5000.0)
        self.assertEqual(summary["initial_bracket"]["low"]["evaluation_id"],
                         "eval-000001")
        self.assertEqual(summary["initial_bracket"]["high"]["evaluation_id"],
                         "eval-000002")
        self.assertEqual(summary["final_bracket_before_accepted_solution"]["low"]["evaluation_id"],
                         "eval-000021")
        self.assertEqual(summary["final_bracket_before_accepted_solution"]["high"]["evaluation_id"],
                         "eval-000020")
        self.assertEqual(summary["accepted_solution"]["evaluation_id"], "eval-000022")
        self.assertEqual(summary["initial_bracket"]["low"]["f_N"],
                         -3716.586891415036)
        self.assertTrue(summary["initial_bracket"]["sign_change"])

    def test_mixed_tuple_is_rejected(self):
        calibration = self._calibration()
        calibration["final_bracket_low_f_N"] = calibration["initial_low_f_N"]
        with self.assertRaises(ValueError):
            _summary_states(calibration, 5000.0)

    def test_summary_json_round_trip_preserves_evaluation_ids(self):
        summary = _summary_states(self._calibration(), 5000.0)
        round_trip = json.loads(json.dumps(summary, sort_keys=True))
        self.assertEqual(round_trip["initial_bracket"]["low"]["evaluation_id"],
                         "eval-000001")
        self.assertEqual(round_trip["final_bracket_before_accepted_solution"]["high"]["evaluation_id"],
                         "eval-000020")
        self.assertEqual(round_trip["accepted_solution"]["evaluation_id"],
                         "eval-000022")


if __name__ == "__main__":
    unittest.main()
