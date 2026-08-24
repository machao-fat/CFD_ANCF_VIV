import unittest
from src.coupling.stage4f_d_e5_matlab_worker_probe_replay_v1.validator import *
class T(unittest.TestCase):
 def good(self): return dict(return_code=0,release='2021b',arch='win64',license=1,application_service=True,temp='D:/t',tmp='D:/t',tmpdir='D:/t',prefdir='D:/p')
 def test_probe(self): self.assertTrue(validate_probe(self.good()))
 def test_probe_fail_closed(self):
  for k,v in [('release','2022a'),('license',0),('application_service',False),('temp','C:/t'),('return_code',1)]:
   p=self.good();p[k]=v;self.assertFalse(validate_probe(p));self.assertFalse(may_replay(p))
 def test_replay(self): self.assertTrue(validate_replay(dict(return_code=0,output_exists=True,fresh=True,identity_ok=True,finite=True,attempts=1)))
 def test_replay_failures(self):
  for k,v in [('return_code',1),('output_exists',False),('fresh',False),('identity_ok',False),('finite',False),('attempts',2)]:
   r=dict(return_code=0,output_exists=True,fresh=True,identity_ok=True,finite=True,attempts=1);r[k]=v;self.assertFalse(validate_replay(r))
