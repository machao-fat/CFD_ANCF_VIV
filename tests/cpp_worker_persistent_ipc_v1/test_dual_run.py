from __future__ import annotations

import unittest
from dataclasses import replace

from coupling.cpp_worker_persistent_ipc_v1.dual_run import DualStepRecord, compare_records
from tools.cpp_worker_persistent_ipc_v1.run_matlab_cpp_dual_run_40 import validate_fixture_source
from coupling.cpp_worker_persistent_ipc_v1.protocol import FrameError


def record() -> DualStepRecord:
    values = tuple(float(index) for index in range(3))
    return DualStepRecord("dual_run", "dual_case", 560, 1, 2.20875, 2208750000,
                          values, values, values, values, values, values, values, values, values)


class DualRunTests(unittest.TestCase):
    def test_matching_record_passes_all_required_fields(self) -> None:
        result = compare_records(record(), record())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(set(result["fields"]), {"q", "qdot", "qddot", "internal_force", "external_force", "generalized_force", "predictor", "corrector", "residual"})

    def test_identity_mismatch_is_fail_closed(self) -> None:
        with self.assertRaises(FrameError):
            compare_records(record(), replace(record(), global_step=561))

    def test_nan_and_dimension_mismatch_are_fail_closed(self) -> None:
        with self.assertRaises(FrameError):
            DualStepRecord.from_mapping({**record().to_dict(), "q": [float("nan")]})
        with self.assertRaises(FrameError):
            compare_records(record(), replace(record(), residual=(1.0,)))

    def test_dual_fixture_source_identity_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            validate_fixture_source({"source_step": 603, "source_time_s": 2.2575, "dt_s": 0.00125})
        validate_fixture_source({"source_step": 559, "source_time_s": 2.2075, "dt_s": 0.00125})


if __name__ == "__main__":
    unittest.main()
