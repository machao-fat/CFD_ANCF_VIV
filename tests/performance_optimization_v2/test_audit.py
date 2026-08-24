from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coupling.performance_optimization_v2.audit import AuditError, BatchAuditWriter, resource_snapshot


class AuditTests(unittest.TestCase):
    def test_batch_keeps_final_artifacts(self):
        root = Path(tempfile.mkdtemp()); writer = BatchAuditWriter(root, batch_size=2)
        writer.append({"step": 1}); writer.append({"step": 2}); writer.append({"step": 3})
        result = writer.finalize(checkpoint={"committed": True, "step": 3}, raw_snapshot={"committed": True, "step": 3}, gate={"committed": True, "gate": "pending"})
        self.assertEqual(len(result), 3); self.assertEqual(len((root / "events.jsonl").read_text(encoding="utf-8").splitlines()), 3)
        self.assertEqual(json.loads((root / "checkpoint_final.json").read_text(encoding="utf-8"))["step"], 3)

    def test_invalid_final_fails_closed(self):
        writer = BatchAuditWriter(Path(tempfile.mkdtemp()))
        with self.assertRaises(AuditError): writer.finalize(checkpoint={"committed": False}, raw_snapshot={}, gate={})

    def test_resource_snapshot_is_read_only(self):
        snapshot = resource_snapshot(Path(tempfile.mkdtemp())); self.assertIn("disk_bytes", snapshot); self.assertEqual(snapshot["processes"], [])


if __name__ == "__main__": unittest.main()
