from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "cpp_worker_confirm_v1" / "run_authorized_confirm_001.py"
SPEC = importlib.util.spec_from_file_location("authorized_confirm_gate_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AuthorizedConfirmGateTests(unittest.TestCase):
    @staticmethod
    def _summary() -> dict[str, object]:
        return {
            "status": "pass", "owned_residual": 0, "cpp_worker_startup": 1,
            "openfoam_startup": 3, "wsl_startup": 3,
            "real_process_starts": {"MATLAB": 0, "OpenFOAM": 3, "WSL": 3, "CFD": 3},
        }

    @staticmethod
    def _processes() -> list[dict[str, object]]:
        return [
            {"component": "worker", "return_code": 0, "cleanup_result": "closed", "start_count": 1},
            *[{"component": "slice", "return_code": 0, "cleanup_result": "closed", "start_count": 1}
              for _ in range(3)],
        ]

    def test_gate_requires_clean_stop_and_all_expected_processes(self) -> None:
        summary = self._summary()
        rows = self._processes()
        logs = {"slice0.log": True, "slice1.log": True, "slice2.log": True}
        checkpoints = [{} for _ in range(40)]
        self.assertTrue(MODULE._gate_ok(summary, {"errors": []}, rows, logs, checkpoints))
        for mutation in (
            ("stop",), ("worker_return",), ("slice_return",), ("slice_starts",), ("worker_starts",),
        ):
            with self.subTest(mutation=mutation):
                changed_summary = dict(summary)
                changed_rows = [dict(row) for row in rows]
                stop = {"errors": []}
                if mutation == ("stop",):
                    stop["errors"] = ["worker exit 17"]
                elif mutation == ("worker_return",):
                    changed_rows[0]["return_code"] = 17
                elif mutation == ("slice_return",):
                    changed_rows[2]["return_code"] = 9
                elif mutation == ("slice_starts",):
                    changed_summary["openfoam_startup"] = 2
                else:
                    changed_summary["cpp_worker_startup"] = 2
                self.assertFalse(MODULE._gate_ok(changed_summary, stop, changed_rows, logs, checkpoints))


if __name__ == "__main__":
    unittest.main()
