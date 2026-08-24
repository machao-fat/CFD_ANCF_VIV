import tempfile, unittest
from pathlib import Path
from src.coupling.stage4f_d_extended_transient_entry_design_v1.runner import build_design,canonical_hash
class TestStage41(unittest.TestCase):
 def test_contract_and_boundaries(self):
  with tempfile.TemporaryDirectory() as d:
   x=build_design(d); self.assertEqual(x['physical_timescale_audit']['Re'],100.0); self.assertFalse(x['current_window_coverage']['frequency_evaluable']); self.assertEqual(x['hard_stop_conditions']['cfl_ge'],.8); self.assertEqual(x['entry_recommendation']['recommendation'],'enter_one_bounded_pilot_pending_user_authorization')
 def test_hash_and_forbidden_scope(self):
  with tempfile.TemporaryDirectory() as d:
   x=build_design(d); self.assertEqual(x['parent_checkpoint_sha256'], '5db86ae104015d51a8268862a1551579d96d0ddc7f55536371efc0334e'); self.assertEqual(canonical_hash(x['recommended_pilot_contract']),x['contract_hash']); self.assertEqual(x['claim_boundary']['five_slice'],'do_not_enter')
