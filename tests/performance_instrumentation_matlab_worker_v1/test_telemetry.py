from __future__ import annotations

import unittest

from coupling.performance_instrumentation_matlab_worker_v1.telemetry import TraceRecorder, summarize_traces


class TelemetryTests(unittest.TestCase):
    def test_trace_contains_required_step_and_phase_fields(self):
        recorder = TraceRecorder()
        for step in range(4):
            start = 1000 + step * 100
            recorder.record(run_id="run93", case_id="case93", global_step=step, case_local_bridge_step=step,
                            time_s=(step + 1) * .0025, integer_tick=(step + 1) * 2500000,
                            request_id=f"r{step}", transaction_id=f"t{step}",
                            phases_ns={"matlab_prediction": (start, start + 10), "openfoam_solve": (start + 10, start + 30)},
                            slice_events=[{"slice_id": 0, "return_code": 0}], process_audits=[], owned_residual=0)
        summary = summarize_traces(recorder.traces)
        self.assertEqual(summary["steps"], 4)
        self.assertIn("matlab_prediction", summary["phase_s"])
        self.assertEqual(summary["external_process_starts"], 0)
        self.assertEqual(summary["owned_residual_max"], 0)


if __name__ == "__main__":
    unittest.main()
