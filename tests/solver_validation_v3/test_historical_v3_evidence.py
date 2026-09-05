"""Historical evidence is read-only and V3 preserves V2 identity."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "results/385_three_slice_statistical_contract_v2_phase_reanalysis_v2"
V3 = ROOT / "results/solver_validation_v3"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class HistoricalV3EvidenceTest(unittest.TestCase):
    def test_stage385_is_immutable(self) -> None:
        self.assertEqual(sha(V2 / "stage4f_d_three_slice_statistical_contract_v2_phase_reanalysis_v2_gate.json"), "CD5D9695788DB29B403A1A5E053F4A2DED6DFAEA08CCD0398673DE0E798D83B3")
        self.assertEqual(sha(V2 / "three_slice_statistical_contract_v2.json"), "0AAB56537B88669B53BAAA399A74CC2F182FB3808FA1006766560DE7C668C0A4")

    def test_v3_has_required_local_windows_and_layered_gate(self) -> None:
        data = json.loads((V3 / "three_slice_statistical_contract_v3.json").read_text(encoding="utf-8"))
        gate = json.loads((V3 / "three_slice_statistical_contract_v3_gate.json").read_text(encoding="utf-8"))
        windows = [[window["start_time_s"], window["end_time_s"] + 0.05] for window in data["windows"]]
        self.assertEqual(windows, [[220.0, 270.0], [270.0, 320.0], [320.0, 370.0], [270.0, 370.0], [220.0, 370.0]])
        self.assertEqual(data["metadata"]["interface_coordinate_semantics"]["value"], "absolute_ANCF_projected_position")
        for key in ("DATA_INTEGRITY", "MAPPING_INTEGRITY", "LOCAL_STATISTICAL_STABILITY", "LOCAL_FLUID_STRUCTURE_SYNCHRONIZATION", "SLICE_PHASE_COHERENCE", "PHYSICAL_FORCE_SCALING"):
            self.assertIn(key, gate)
        self.assertEqual(gate["SLICE_PHASE_COHERENCE"], "diagnostic")
        self.assertEqual(gate["PHYSICAL_FORCE_SCALING"], "not_evaluable")


if __name__ == "__main__":
    unittest.main()
