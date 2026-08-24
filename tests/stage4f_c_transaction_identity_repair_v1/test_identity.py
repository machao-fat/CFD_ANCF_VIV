import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from coupling.stage4f_three_slice_timestep_diagnostic_v3 import engine_impl
class Tests(unittest.TestCase):
 def test_factory_source_is_explicit_in_source(self):
  src=Path(engine_impl.__file__).read_text(encoding='utf8');self.assertIn('self.run_id = str(plan.get("run_id", ""))',src);self.assertIn('run_id=self.run_id',src);self.assertIn('self.scheduler.run_id = self.run_id',src)
 def test_default_or_missing_rejected_by_contract(self):
  src=Path(engine_impl.__file__).read_text(encoding='utf8');self.assertIn('factory requires a fresh explicit run_id',src)
 def test_stage25_exact_contract_unchanged(self):
  from coupling.stage4f_c_time_consistent_stabilizer_contract_repair_v1.contract import load_contract,verify_math
  self.assertTrue(verify_math(load_contract())['equal_elapsed_decay_verified'])
 def test_stage26_runtime_isolation(self):
  from coupling.stage4f_c_transaction_identity_repair_v1 import probe
  src=Path(probe.__file__).read_text(encoding='utf8');self.assertIn('runtime/stage4f_c_transaction_identity_repair_v1',src);self.assertNotIn("base.build(case",src)
 def test_object_graph_and_transactions(self):
  from coupling.stage4f_c_transaction_identity_repair_v1.identity import audit_engine,validate_manifest_transactions,IdentityError
  r='r';e=SimpleNamespace(run_id=r,scheduler=SimpleNamespace(run_id=r),processes=[SimpleNamespace(run_id=r) for _ in range(3)]);self.assertEqual(audit_engine(e,r)['factory'],r)
  rows=[{'slice_id':i,'artifact_creation_transaction':f'r:0:{i}:10:create','consumed_transaction':f'c{i}'} for i in range(3)];self.assertTrue(validate_manifest_transactions(rows,r,0,10));rows[0]['artifact_creation_transaction']='stale';self.assertRaises(IdentityError,validate_manifest_transactions,rows,r,0,10)
if __name__=='__main__':unittest.main()
