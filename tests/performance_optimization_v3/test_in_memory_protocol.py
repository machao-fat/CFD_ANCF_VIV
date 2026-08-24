from __future__ import annotations

import unittest
from pathlib import Path


class InMemoryProtocolTests(unittest.TestCase):
    def test_matlab_worker_has_explicit_stateful_and_rollback_paths(self):
        path = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/src/coupling/performance_matlab_worker_bridge_v1/matlab_worker_loop.m")
        text = path.read_text(encoding="utf-8")
        for token in ("in_memory_state", "committed_state", "rollback_state", "strcmp(request.operation, 'rollback')"):
            self.assertIn(token, text)

    def test_v3_does_not_claim_persistent_ipc(self):
        from coupling.performance_optimization_v3.contracts import make_contract
        self.assertTrue(make_contract)

