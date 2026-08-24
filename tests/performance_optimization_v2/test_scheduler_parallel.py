from __future__ import annotations

import time
import unittest

from coupling.multi_slice_driver.scheduler import MultiSliceScheduler


class SchedulerParallelTests(unittest.TestCase):
    def test_parallel_slice_map_is_barrier_normalized(self):
        scheduler = object.__new__(MultiSliceScheduler)
        scheduler.parallel_slices = True
        started = time.perf_counter()
        result = scheduler._parallel_slice_map(lambda sid: (time.sleep(0.03), sid)[1], [0, 1, 2])
        elapsed = time.perf_counter() - started
        self.assertEqual(result, {0: 0, 1: 1, 2: 2})
        self.assertLess(elapsed, 0.15)

    def test_sequential_mode_remains_available(self):
        scheduler = object.__new__(MultiSliceScheduler)
        scheduler.parallel_slices = False
        order: list[int] = []
        result = scheduler._parallel_slice_map(lambda sid: order.append(sid) or sid, [2, 0, 1])
        self.assertEqual(result, {2: 2, 0: 0, 1: 1})
        self.assertEqual(order, [2, 0, 1])


if __name__ == "__main__":
    unittest.main()
