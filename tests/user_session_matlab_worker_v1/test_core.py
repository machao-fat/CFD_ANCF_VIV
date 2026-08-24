from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from coupling.user_session_matlab_worker_v1.core import UserSessionWorker, atomic_json, canonical_bytes, contract_hash


class CoreTests(unittest.TestCase):
    def make_contract(self, root: Path) -> dict:
        runtime = root / "runtime" / "user_session_matlab_worker_v1"; request = runtime / "requests"; response = runtime / "responses"
        run_id = "run94-worker-" + uuid.uuid4().hex
        result = {"contract_version": "user-session-matlab-worker.1", "run_id": run_id, "case_id": "case94-worker", "stage_id": "stage94", "expected_session_id": 1, "expected_username": "Administrator", "matlab_executable": "D:/MATLAB/R2021b/bin/matlab.exe", "expected_release": "2021b", "expected_architecture": "win64", "runtime": str(runtime), "request_dir": str(request), "response_dir": str(response), "no_cfd": True, "no_openfoam": True, "no_wsl": True, "no_retry": True, "worker_only": True}
        result["contract_sha256"] = contract_hash(result); return result

    def test_validates_without_launching_process(self):
        root = Path("D:/stage94_project")
        runtime = Path("D:/stage94_project/runtime/runner_valid"); runner = UserSessionWorker(project_root=root, runtime=runtime, launcher=lambda *a, **k: self.fail("launcher called"))
        contract = self.make_contract(root); inbox = runtime / "inbox" / "run94-worker.json"; atomic_json(inbox, contract)
        result = runner.accept(inbox, launch=False)
        self.assertEqual(result["gate"], "offline_contract_validated")
        self.assertEqual(result["external_process_starts"], 0)

    def test_rejects_hash_and_session_mismatch(self):
        root = Path("D:/stage94_project")
        runtime = Path("D:/stage94_project/runtime/runner_bad"); runner = UserSessionWorker(project_root=root, runtime=runtime)
        contract = self.make_contract(root); contract["expected_session_id"] = 2
        atomic_json(runtime / "inbox" / "bad.json", contract)
        result = runner.accept(runtime / "inbox" / "bad.json", launch=False)
        self.assertEqual(result["state"], "CONTRACT_REJECTED")


if __name__ == "__main__":
    unittest.main()
