import math, unittest
from coupling.stage4f_c_time_consistent_stabilizer_production_v1.hook import TAU_S,STATE_SCHEMA,TimeConsistentLoadStabilizer,StabilizationGateError
class Tests(unittest.TestCase):
 def test_decay_equivalence(self): self.assertAlmostEqual(math.exp(-.0025/TAU_S),math.exp(-.00125/TAU_S)**2,15)
 def test_tau_full_precision(self): self.assertEqual(TAU_S,-.0025/math.log(.9))
 def test_explicit_schema_and_wrong_identity(self):
  h=TimeConsistentLoadStabilizer(slice_force_scales_N={0:1});s=h.initialize_from_legacy({'previous_slice_forces_N':[[0,0,0]],'step':2,'time_s':1.5075},run_id='r',case_id='c');self.assertEqual(s['schema'],STATE_SCHEMA);self.assertRaises(StabilizationGateError,h._validate_state,s,'x','c')
 def test_wrong_tau_and_mixed_state_fail(self):
  h=TimeConsistentLoadStabilizer(slice_force_scales_N={0:1});s=h.initialize_from_legacy({'previous_slice_forces_N':[[0,0,0]],'step':2,'time_s':1.5075},run_id='r',case_id='c');s['tau_s']=1;self.assertRaises(StabilizationGateError,h._validate_state,s,'r','c');s['tau_s']=TAU_S;s['schema']='old';self.assertRaises(StabilizationGateError,h._validate_state,s,'r','c')
if __name__=='__main__':unittest.main()
