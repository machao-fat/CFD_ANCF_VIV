import json,math,unittest
from decimal import Decimal
from coupling.stage4f_c_integer_serialization_repair_v1.integer import exact_int,roundtrip
from coupling.checkpoint.atomic_checkpoint import _state_tree
class Tests(unittest.TestCase):
 def test_boundaries(self):
  for v in (0,2**53-1,2**53,2**53+1,1787117033409236800,2**63-1,2**80):self.assertEqual(roundtrip(v),(v,'int',True));self.assertEqual(_state_tree(v,'x'),v)
 def test_numpy(self):
  import numpy as np
  for v in (np.int64(2**63-1),np.uint64(2**64-1)):self.assertIsInstance(_state_tree(v,'x'),int)
 def test_invalid(self):
  for v in (True,1.0,1.5,Decimal(1),"1","01","1e3",""):
   with self.assertRaises(ValueError):exact_int(v,'x')
 def test_json_roundtrip_type(self):
  v=1787117033409236800;x=json.loads(json.dumps({'mtime_ns':_state_tree(v,'x')}));self.assertEqual(x['mtime_ns'],v);self.assertIsInstance(x['mtime_ns'],int)
 def test_stage26_classification(self):
  self.assertNotEqual(int(float(1787117033409236800)),1787117033409236800)
if __name__=='__main__':unittest.main()
