from __future__ import annotations

import sys
import time
import unittest

from src.coupling.process_control import ProcessLimiter, ProcessLimiterError


def child_command(seconds: float, exit_code: int = 0) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds!r}); raise SystemExit({exit_code})"]


class ProcessLimiterTests(unittest.TestCase):
    def test_max_one_blocks_and_releases(self) -> None:
        limiter = ProcessLimiter(1, run_id="test-max1")
        first = limiter.launch(child_command(0.12), slice_id=0, global_step=0)
        started = time.monotonic()
        second = limiter.launch(child_command(0.01), slice_id=1, global_step=0, timeout_s=2.0)
        elapsed = time.monotonic() - started
        first.wait(2.0)
        second.wait(2.0)
        audit = limiter.audit()
        limiter.shutdown()
        self.assertGreaterEqual(elapsed, 0.08)
        self.assertEqual(audit["interval_peak_active_count"], 1)
        self.assertEqual(audit["peak_active_count"], 1)
        self.assertFalse(audit["permit_leak"])

    def test_three_processes_max_two_and_real_overlap(self) -> None:
        limiter = ProcessLimiter(2, run_id="test-max2")
        children = [limiter.launch(child_command(0.15), slice_id=i, global_step=3, timeout_s=2.0) for i in range(3)]
        for child in children:
            self.assertEqual(child.wait(2.0), 0)
        audit = limiter.audit()
        limiter.shutdown()
        self.assertEqual(audit["interval_peak_active_count"], 2)
        self.assertLessEqual(audit["peak_active_count"], 2)
        self.assertEqual(len(audit["records"]), 3)
        self.assertTrue(all(item["start_time_ns"] < item["end_time_ns"] for item in audit["records"]))

    def test_nonzero_exit_releases_permit(self) -> None:
        limiter = ProcessLimiter(1, run_id="test-failure")
        child = limiter.launch(child_command(0.01, 7), slice_id=0, global_step=1)
        self.assertEqual(child.wait(2.0), 7)
        audit = limiter.audit()
        limiter.shutdown()
        self.assertEqual(audit["records"][0]["exit_code"], 7)
        self.assertEqual(audit["records"][0]["condition"], "failed")
        self.assertFalse(audit["permit_leak"])

    def test_timeout_releases_permit(self) -> None:
        limiter = ProcessLimiter(1, run_id="test-timeout")
        child = limiter.launch(child_command(2.0), slice_id=0, global_step=2)
        with self.assertRaises(TimeoutError):
            child.wait(0.05)
        limiter.assert_no_leaks()
        limiter.shutdown()

    def test_leak_and_shutdown_are_fail_closed(self) -> None:
        limiter = ProcessLimiter(1, run_id="test-leak")
        permit = limiter.acquire(slice_id=0, global_step=0)
        with self.assertRaises(ProcessLimiterError):
            limiter.shutdown()
        permit.release(exit_code=None, condition="test_release")
        limiter.shutdown()


if __name__ == "__main__":
    unittest.main()
