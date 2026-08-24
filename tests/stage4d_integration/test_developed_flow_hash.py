from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4d_campaign.developed_flow import DevelopedFlowError, audit_developed_flow_identity


ROOT = Path(__file__).resolve().parents[2]


class DevelopedFlowHashTests(unittest.TestCase):
    def test_existing_flow_hashes_recompute(self) -> None:
        for flow_id in ("re80", "re100", "re120"):
            summary_path = ROOT / "results" / "06_developed_flow" / flow_id / f"{flow_id}_summary.json"
            case = ROOT / "cases" / "openfoam" / "stage4d_developed_flow" / flow_id
            if not summary_path.is_file():
                self.skipTest(f"developed flow {flow_id} has not been run")
            audit = audit_developed_flow_identity(json.loads(summary_path.read_text(encoding="utf-8")), case=case)
            self.assertEqual(audit["status"], "passed")

    def test_tampered_field_is_rejected(self) -> None:
        flow_id = "re100"
        summary_path = ROOT / "results" / "06_developed_flow" / flow_id / f"{flow_id}_summary.json"
        case = ROOT / "cases" / "openfoam" / "stage4d_developed_flow" / flow_id
        if not summary_path.is_file():
            self.skipTest("developed flow has not been run")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        relative = next(iter(summary["final_fields"]))
        source = case / relative
        tampered = Path(tempfile.mkdtemp(prefix="stage4d_tamper_")) / Path(relative).name
        tampered.write_bytes(source.read_bytes() + b"\nTAMPERED\n")
        changed = dict(summary)
        changed["final_fields"] = dict(summary["final_fields"])
        changed["final_fields"][relative] = "0" * 64
        with self.assertRaises(DevelopedFlowError):
            audit_developed_flow_identity(changed, case=case)
        self.assertNotEqual(tampered.read_bytes(), source.read_bytes())


if __name__ == "__main__":
    unittest.main()
