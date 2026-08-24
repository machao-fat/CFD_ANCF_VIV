from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from coupling.performance_optimization_v2.contracts import canonical_bytes, contract_hash
from coupling.performance_optimization_v2.openfoam_persistent import persistent_ready_timeout, PersistentOpenFOAMError
from coupling.performance_optimization_v2.real_coordinator import (
    RealCoordinatorError,
    detect_applicationservice_5001,
    run_contract,
)


class RealCoordinatorGuardTests(unittest.TestCase):
    def test_only_explicit_applicationservice_5001_requests_user_runner(self):
        self.assertTrue(detect_applicationservice_5001(("MATLAB ApplicationService returned error 5001",)))
        self.assertTrue(detect_applicationservice_5001(("Error 5001 while starting MATLAB",)))
        self.assertFalse(detect_applicationservice_5001(("Java is shutting down", "return code=1")))
        self.assertFalse(detect_applicationservice_5001(("license test returned 0",)))
        self.assertFalse(detect_applicationservice_5001(("generic error 5001",)))

    def test_persistent_ready_timeout_is_bounded_and_longer_than_legacy(self):
        self.assertEqual(persistent_ready_timeout(90.0), 360.0)
        self.assertEqual(persistent_ready_timeout(1.0), 30.0)
        self.assertEqual(persistent_ready_timeout(1000.0), 600.0)

    def test_persistent_ready_timeout_rejects_nonpositive(self):
        with self.assertRaises(PersistentOpenFOAMError):
            persistent_ready_timeout(0.0)

    def test_ipc_factor_fails_before_external_launch(self):
        project = Path(__file__).resolve().parents[2]
        source_contract = json.loads((project / "runtime/performance_optimization_v2/inbox/B_002_contract.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=str(project / "runtime/performance_optimization_v2")) as temp:
            contract = dict(source_contract)
            contract.update({"configuration_label": "I", "factors": ["I"],
                             "run_id": "run95_i_guard", "case_id": "case95_i_guard",
                             "runtime": str(Path(temp).resolve())})
            contract["contract_sha256"] = contract_hash(contract)
            path = Path(temp) / "contract.json"
            path.write_bytes(canonical_bytes(contract))
            # The guard is intentionally evaluated before source validation
            # and process creation; no launcher or CFD executable may be
            # reached.
            with patch("coupling.performance_optimization_v2.real_coordinator.subprocess.Popen") as launch:
                with self.assertRaises(RealCoordinatorError) as raised:
                    run_contract(path)
                self.assertIn("persistent IPC", str(raised.exception))
                launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
