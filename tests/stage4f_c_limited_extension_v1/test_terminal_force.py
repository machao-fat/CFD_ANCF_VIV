import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.coupling.multi_slice_driver.real_process import ExactForce, RealProcessFreshnessError
from src.coupling.stage4f_c_limited_extension_v1.terminal_force import refresh_terminal_force


class Popen:
    def wait(self, timeout=None): return 0


class Process:
    def __init__(self, path, target):
        self.path = path; self.process = Popen(); self.runtime_config = SimpleNamespace(timeout_s=1)
        self.slice_id = 0; self.last_force = ExactForce(target, (3.0, 0.0, 0.0), 1, 1); self.last_force_fingerprint = None
    def _force_path(self, time_s): return self.path


def row(time):
    return f"{time} ((1 0 0) (2 0 0) (0 0 0)) ((0 0 0) (0 0 0) (0 0 0))\n"


class TerminalLastRowTests(unittest.TestCase):
    def test_target_as_last_complete_row_passes(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "forces.dat"; path.write_text(row(1.0), encoding="utf-8")
            refresh_terminal_force(Process(path, 1.0), time_s=1.0)

    def test_later_complete_row_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "forces.dat"; path.write_text(row(1.0) + row(1.1), encoding="utf-8")
            with self.assertRaises(RealProcessFreshnessError):
                refresh_terminal_force(Process(path, 1.0), time_s=1.0)


if __name__ == "__main__": unittest.main()
