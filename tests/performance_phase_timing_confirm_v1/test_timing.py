from __future__ import annotations

import time
import unittest

from coupling.performance_phase_timing_confirm_v1 import PhaseTimingError, PhaseTimingRecorder, summarize_phase_records


def _row(step: int = 560):
    recorder = PhaseTimingRecorder(
        run_id="performance_phase_timing_confirm_001", case_id="performance_phase_timing_case_001",
        source_global_step=559, source_time_s=2.2075, source_tick=2207500000, dt_s=0.00125,
    )
    recorder.begin_step(step, 2.2075 + (step - 559) * 0.00125)
    recorder.ancf_start(step); time.sleep(0.00001); recorder.exchange_start(step)
    recorder.openfoam_start(step, 0); time.sleep(0.00001); recorder.openfoam_end(step, 0)
    recorder.openfoam_start(step, 1); time.sleep(0.00002); recorder.openfoam_end(step, 1)
    recorder.openfoam_start(step, 2); time.sleep(0.00001); recorder.openfoam_end(step, 2)
    recorder.exchange_end(step); recorder.ancf_end(step); recorder.sync_audit_end(step)
    recorder.end_step(step)
    return recorder.finalize(step=step, expected_time_s=2.2075 + (step - 559) * 0.00125)


class PhaseTimingTests(unittest.TestCase):
  def test_records_have_required_timestamps_and_barrier_metrics(self):
    row = _row()
    assert row["global_step"] == 560
    assert row["case_local_bridge_step"] == 1
    assert row["integer_tick"] == 2208750000
    assert set(row["openfoam_timestamps_ns"]) == {"0", "1", "2"}
    assert row["durations_s"]["T_openfoam"] >= row["durations_s"]["T_openfoam_slice_sum"] / 3.0
    assert row["barrier_wait_s"] >= 0.0


  def test_summary_contains_all_statistics_and_overlap(self):
    records = [_row(560), _row(561)]
    summary = summarize_phase_records(records)
    assert summary["steps"] == 2
    for name in ("T_ancf", "T_openfoam", "T_exchange", "T_sync_and_audit", "T_step", "overlap_gap"):
        assert {"mean_s", "p50_s", "p95_s", "max_s", "min_s", "stddev_s"} <= set(summary["phase_s"][name])
    assert summary["slice_s"]["1"]["mean_s"] > 0.0
    self.assertEqual(records[0]["request_id"], "performance_phase_timing_motion_00000560")

  def test_duplicate_or_out_of_order_steps_fail_closed(self):
    first = _row(560)
    with self.assertRaises(PhaseTimingError):
      summarize_phase_records([first, dict(first)])

  def test_tick_identity_mismatch_fails_closed(self):
    with self.assertRaises(PhaseTimingError):
      first, second = _row(560), _row(561)
      second["integer_tick"] += 1
      summarize_phase_records([first, second])


  def test_missing_or_non_monotonic_timestamp_fails_closed(self):
    recorder = PhaseTimingRecorder(run_id="r", case_id="c", source_global_step=559,
                                   source_time_s=2.2075, source_tick=2207500000, dt_s=0.00125)
    recorder.begin_step(560, 2.20875)
    recorder.ancf_start(560); recorder.ancf_end(560)
    with self.assertRaises(PhaseTimingError):
        recorder.finalize(step=560, expected_time_s=2.20875)


if __name__ == "__main__":
    unittest.main()
