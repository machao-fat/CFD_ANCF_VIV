from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from coupling.performance_optimization_v2.real_coordinator import submit_matlab_start


class StartupOverlapTests(unittest.TestCase):
    def test_matlab_start_is_submitted_before_case_setup_continues(self):
        entered = threading.Event()
        release = threading.Event()
        case_setup_marker = threading.Event()

        def fake_start(contract, runtime):
            entered.set()
            self.assertTrue(release.wait(2.0))
            return object(), {"component": "matlab_persistent_worker"}, object()

        with patch("coupling.performance_optimization_v2.real_coordinator._start_matlab", fake_start):
            executor, future = submit_matlab_start({}, Path("D:/stage96-test-runtime"))
            try:
                self.assertTrue(entered.wait(2.0))
                # This represents independent case skeleton/restart setup. It
                # is allowed to proceed while the worker startup is pending.
                case_setup_marker.set()
                self.assertTrue(case_setup_marker.is_set())
                self.assertFalse(future.done())
                release.set()
                process, audit, stream = future.result(timeout=2.0)
                self.assertEqual(audit["component"], "matlab_persistent_worker")
                self.assertIsNotNone(process)
                self.assertIsNotNone(stream)
            finally:
                release.set()
                executor.shutdown(wait=True)

    def test_startup_failure_remains_visible_to_resolver(self):
        def fail_start(contract, runtime):
            raise RuntimeError("probe failed")

        with patch("coupling.performance_optimization_v2.real_coordinator._start_matlab", fail_start):
            executor, future = submit_matlab_start({}, Path("D:/stage96-test-runtime"))
            try:
                with self.assertRaisesRegex(RuntimeError, "probe failed"):
                    future.result(timeout=2.0)
            finally:
                executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
