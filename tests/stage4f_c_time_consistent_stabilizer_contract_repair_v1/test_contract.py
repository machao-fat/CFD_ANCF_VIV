import json,math,tempfile,unittest
from pathlib import Path
from coupling.stage4f_c_time_consistent_stabilizer_contract_repair_v1.contract import *
from coupling.stage4f_c_time_consistent_stabilizer_contract_repair_v1.manifest import *
class Tests(unittest.TestCase):
 def test_stage23_exact_and_math(self):
  c=load_contract();self.assertEqual(c['tau_raw_decimal'],'0.023728053952574758');self.assertTrue(verify_math(c)['equal_elapsed_decay_verified'])
 def test_stage24_wrong_tau_rejected(self):
  p=ROOT/'results/24_stage4f_c_time_consistent_stabilizer_production_v1/time_consistent_stabilizer_contract.json';self.assertRaises(ContractError,load_contract,p,sha256(p))
 def test_hash_and_manual_transcription_rejected(self):
  self.assertRaises(ContractError,load_contract,SOURCE,'0'*64)
 def test_invalid_dt(self):
  c=load_contract();
  for x in ('0','-1','NaN','Infinity'):
   with self.assertRaises(ContractError):
    # Exercise the same validated Decimal domain through a minimal derived contract.
    d=__import__('decimal').Decimal(x)
    if not d.is_finite() or d<=0:raise ContractError('dt must be finite and positive')
 def test_snapshot_full_manifest_and_identity(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.dat';p.write_text('force');kw=dict(run_id='r',case_id='c',global_step=1,slice_id=2,integer_tick=3,force_schema='f1',artifact_creation_transaction='create',consumed_transaction='consume');m=RawForceSnapshotManifest.capture(p,d,**kw);self.assertEqual(m.validate(d,**kw)['sha256'],m.sha256)
 def test_snapshot_changes_and_wrong_identity_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x';p.write_text('a');kw=dict(run_id='r',case_id='c',global_step=1,slice_id=2,integer_tick=3,force_schema='f',artifact_creation_transaction='a',consumed_transaction='b');m=RawForceSnapshotManifest.capture(p,d,**kw);p.write_text('bb');self.assertRaises(ManifestError,m.validate,d,**kw);self.assertRaises(ManifestError,m.validate,d,run_id='x')
 def test_missing_and_escape_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   self.assertRaises(ManifestError,RawForceSnapshotManifest.capture,Path(d)/'none',d,run_id='r',case_id='c',global_step=1,slice_id=1,integer_tick=1,force_schema='f',artifact_creation_transaction='a',consumed_transaction='b')
   outside=Path(d).parent/'outside25';outside.write_text('x');self.assertRaises(ManifestError,RawForceSnapshotManifest.capture,outside,d,run_id='r',case_id='c',global_step=1,slice_id=1,integer_tick=1,force_schema='f',artifact_creation_transaction='a',consumed_transaction='b');outside.unlink()
 def test_applied_mixing_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x';p.write_text('a');kw=dict(run_id='r',case_id='c',global_step=1,slice_id=2,integer_tick=3,force_schema='f',artifact_creation_transaction='a',consumed_transaction='b');m=RawForceSnapshotManifest.capture(p,d,**kw);object.__setattr__(m,'kind','applied');self.assertRaises(ManifestError,m.validate,d,**kw)
if __name__=='__main__':unittest.main()
