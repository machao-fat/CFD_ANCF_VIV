from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coupling.performance_optimization_v3.audit import audit_result


class AuditProtectionTests(unittest.TestCase):
    def test_incomplete_result_fails_closed(self):
        with tempfile.TemporaryDirectory(dir="D:/") as temp:
            root = Path(temp)
            result = root / "result.json"; result.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
            gate = audit_result(result, root / "out")
            self.assertTrue(gate["gate"].endswith(": do_not_pass"))
            self.assertTrue(gate["errors"])

