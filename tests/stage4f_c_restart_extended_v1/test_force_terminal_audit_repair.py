from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.coupling.multi_slice_driver.real_process import (
    ExactForce,
    RealProcessFreshnessError,
    force_file_audit,
    parse_force_exact,
)
from src.coupling.stage4f_c_restart_extended_v1.force_terminal_audit_repair import (
    CandidateIterationEngine,
    refresh_terminal_force,
)


TARGET_TIME = 1.50875


def _force_row(time_s: float, pressure=(1.0, 2.0, 3.0), viscous=(0.1, 0.2, 0.3)) -> str:
    p = " ".join(str(value) for value in pressure)
    v = " ".join(str(value) for value in viscous)
    return f"{time_s:.12g} (({p}) ({v}) (0 0 0))\n"


def _force_row_precise(time_s: float) -> str:
    return f"{time_s:.16g} ((1 2 3) (0.1 0.2 0.3) (0 0 0))\n"


class _OwnedSolver:
    def __init__(self, return_code: int = 0):
        self.returncode = None
        self._return_code = return_code
        self.wait_calls = 0

    def wait(self, timeout=None):
        self.wait_calls += 1
        self.returncode = self._return_code
        return self._return_code

    def poll(self):
        return self.returncode


class _FakeSliceProcess:
    def __init__(self, root: Path, *, slice_id: int = 0, return_code: int = 0):
        self.slice_id = slice_id
        self.case = root
        root.mkdir(parents=True, exist_ok=True)
        self.runtime_config = SimpleNamespace(timeout_s=1.0)
        self.process = _OwnedSolver(return_code)
        self.force_path = root / "forces.dat"
        self.force_path.write_text(_force_row(TARGET_TIME), encoding="utf-8")
        parsed = parse_force_exact(self.force_path, target_time_s=TARGET_TIME)
        assert parsed is not None
        self.last_force = parsed
        self.finish_calls = 0
        self.force_audits = []

    def _force_path(self, _time_s: float) -> Path:
        return self.force_path

    def finish_step(self, _step: int, time_s: float) -> None:
        self.finish_calls += 1
        code = self.process.wait(timeout=self.runtime_config.timeout_s)
        if code != 0:
            raise RuntimeError(f"slice {self.slice_id} OpenFOAM returned {code}")
        self.force_audits.append(force_file_audit(self._force_path(time_s), expected=self.last_force))


class TerminalForceRefreshTests(unittest.TestCase):
    def test_later_complete_force_row_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = self._process(Path(temporary))
            process.force_path.write_text(
                _force_row(TARGET_TIME) + _force_row(TARGET_TIME + 0.1), encoding="utf-8"
            )
            with self.assertRaises(RealProcessFreshnessError):
                refresh_terminal_force(process, time_s=TARGET_TIME)

    def _process(self, root: Path, *, return_code: int = 0) -> _FakeSliceProcess:
        return _FakeSliceProcess(root, return_code=return_code)

    def test_terminal_mtime_or_size_change_with_identical_target_force_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = self._process(Path(temporary))
            consumed = process.last_force
            process.force_path.write_text(
                "# solver appended harmless terminal output\n" + _force_row(TARGET_TIME),
                encoding="utf-8",
            )
            os.utime(process.force_path, ns=(consumed.mtime_ns + 1_000_000, consumed.mtime_ns + 1_000_000))

            refresh_terminal_force(process, time_s=TARGET_TIME)
            refreshed = process.last_force

            self.assertEqual(refreshed.force_N, consumed.force_N)
            self.assertEqual(refreshed.time_s, consumed.time_s)
            self.assertNotEqual((refreshed.size, refreshed.mtime_ns), (consumed.size, consumed.mtime_ns))
            self.assertIs(process.last_force, refreshed)
            process.finish_step(1, TARGET_TIME)
            self.assertEqual(process.finish_calls, 1)

    def test_changed_target_force_is_rejected_even_when_time_is_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = self._process(Path(temporary))
            process.force_path.write_text(_force_row(TARGET_TIME, pressure=(9.0, 2.0, 3.0)), encoding="utf-8")
            with self.assertRaisesRegex(RealProcessFreshnessError, "force|changed|identity"):
                refresh_terminal_force(process, time_s=TARGET_TIME)
            self.assertEqual(process.finish_calls, 0)

    def test_terminal_time_within_frozen_parser_tolerance_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = self._process(Path(temporary))
            process.force_path.write_text(_force_row_precise(TARGET_TIME + 5.0e-13), encoding="utf-8")
            refresh_terminal_force(process, time_s=TARGET_TIME)
            self.assertAlmostEqual(process.last_force.time_s, TARGET_TIME, delta=1.0e-12)
            self.assertEqual(process.last_force.force_N, (1.1, 2.2, 3.3))

    def test_missing_exact_target_row_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = self._process(Path(temporary))
            process.force_path.write_text(_force_row(TARGET_TIME + 0.01), encoding="utf-8")
            with self.assertRaisesRegex(RealProcessFreshnessError, "target|force|missing"):
                refresh_terminal_force(process, time_s=TARGET_TIME)

    def test_duplicate_exact_target_rows_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = self._process(Path(temporary))
            process.force_path.write_text(_force_row(TARGET_TIME) * 2, encoding="utf-8")
            with self.assertRaisesRegex(RealProcessFreshnessError, "target|force|duplicate"):
                refresh_terminal_force(process, time_s=TARGET_TIME)

    def test_nonzero_solver_return_code_is_rejected_before_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = self._process(Path(temporary), return_code=7)
            with self.assertRaisesRegex(RuntimeError, "returned 7|return code"):
                refresh_terminal_force(process, time_s=TARGET_TIME)
            self.assertEqual(process.process.wait_calls, 1)

    def test_nan_or_inf_in_force_file_is_rejected(self):
        for invalid in ("nan", "inf"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                process = self._process(Path(temporary))
                process.force_path.write_text(
                    _force_row(TARGET_TIME, pressure=(invalid, 2.0, 3.0)), encoding="utf-8",
                )
                with self.assertRaisesRegex(RealProcessFreshnessError, "NaN/Inf"):
                    refresh_terminal_force(process, time_s=TARGET_TIME)

    def test_engine_refreshes_all_processes_then_runs_original_terminal_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processes = []
            for slice_id in range(3):
                process = _FakeSliceProcess(root / f"slice_{slice_id}", slice_id=slice_id)
                consumed = process.last_force
                process.force_path.write_text("# terminal flush\n" + _force_row(TARGET_TIME), encoding="utf-8")
                os.utime(process.force_path, ns=(consumed.mtime_ns + 1_000_000, consumed.mtime_ns + 1_000_000))
                processes.append(process)

            engine = object.__new__(CandidateIterationEngine)
            engine.processes = processes
            engine.physical_step = 1
            engine.target_time_s = TARGET_TIME
            engine._processes_finished = False
            engine._snapshot_processes = lambda: None

            engine._finish_slice_processes()
            engine._finish_slice_processes()

            self.assertTrue(engine._processes_finished)
            self.assertEqual([process.finish_calls for process in processes], [1, 1, 1])
            self.assertEqual([len(process.force_audits) for process in processes], [1, 1, 1])


if __name__ == "__main__":
    unittest.main()
