import tempfile,unittest
from src.coupling.stage4f_d_e2_e3_entry_review_v1.runner import build
class TestReview(unittest.TestCase):
 def test_projection(self):
  with tempfile.TemporaryDirectory() as d:
   x=build(d); e={c['id']:c for c in x['candidates']}; self.assertEqual(e['E2']['steps'],80); self.assertTrue(e['E2']['within_4h']); self.assertFalse(e['E2']['frequency_15_cycles_possible']); self.assertTrue(e['E3']['within_4h']); self.assertFalse(e['E3']['frequency_15_cycles_possible'])
 def test_boundary(self):
  with tempfile.TemporaryDirectory() as d:
   x=build(d); self.assertEqual(x['recommendation'],'enter_E2_pending_user_authorization'); self.assertEqual(x['claim_boundary']['five_slice'],'do_not_enter'); self.assertEqual(x['statistical_contract']['minimum_cycles'],5)
