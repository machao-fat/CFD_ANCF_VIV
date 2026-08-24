import unittest
from pathlib import Path
from coupling.stage4f_c_dt2_impulse_forensic_v1.forensic import load, impulse, A, C
class ForensicTests(unittest.TestCase):
    def test_finite_and_aligned(self):
        a=load(A)['steps']; c=load(C)['steps']; self.assertEqual(len(a),20); self.assertEqual(len(c),40); self.assertEqual(a[-1]['time_s'],c[-1]['time_s'])
    def test_impulse_deterministic(self):
        a=load(A)['steps']; x,_=impulse(a,'raw_slice_forces_N',.0025); y,_=impulse(a,'raw_slice_forces_N',.0025); self.assertEqual(x.tolist(),y.tolist())
if __name__=='__main__': unittest.main()
