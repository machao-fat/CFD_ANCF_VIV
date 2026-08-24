import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_equilibrated_startup_v3.closeout import closeout


class TestCloseout(unittest.TestCase):
    def test_endpoint_cd_over_limit_blocks_fsi(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); log = root / "run" / "cases" / "slice_0000" / "log.pimpleFoam_stage4f_b3_reconciliation"
            log.parent.mkdir(parents=True); log.write_text("Courant Number mean: 0 max: 0.2\nCd    = 11.5\nEnd\n", encoding="utf-8")
            equilibrium = root / "equilibrium.json"; equilibrium.write_text(json.dumps({"static":{"passes":True}}), encoding="utf-8")
            gate = closeout(root / "run", root / "out", equilibrium)
            self.assertFalse(gate["endpoint_force_scale_passed"])
            self.assertFalse(gate["formal_three_slice_fsi_started"])

