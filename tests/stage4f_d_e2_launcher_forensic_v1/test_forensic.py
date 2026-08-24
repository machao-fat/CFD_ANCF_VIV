import json, unittest
from pathlib import Path
from src.coupling.stage4f_d_e2_launcher_forensic_v1.forensic import ROOT, SOURCE
class TestStage47(unittest.TestCase):
 def test_source_identity(self):
  p=json.loads(SOURCE.read_text(encoding='utf-8-sig')); self.assertEqual(p['step'],79); self.assertEqual(p['time_tick'],1607500000); self.assertAlmostEqual(p['time_s'],1.6075)
 def test_stage47_isolation(self): self.assertFalse((ROOT/'cases/openfoam/stage4f_d_e2_launcher_forensic_v1').samefile(ROOT/'cases/openfoam/stage4f_d_e2_motion_initialization_repair_v1'))
