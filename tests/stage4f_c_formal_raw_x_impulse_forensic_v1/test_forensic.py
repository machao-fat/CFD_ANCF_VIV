import unittest
from src.coupling.stage4f_c_formal_raw_x_impulse_forensic_v1.forensic import integrate

class Tests(unittest.TestCase):
    def test_quadrature(self):
        t=[0,1_000_000_000,3_000_000_000]; f=[[0,0,0],[2,4,0],[4,8,0]]
        self.assertEqual(integrate(t,f,'trapezoid'),[7,14,0])
        self.assertEqual(integrate(t,f,'left'),[4,8,0])
        self.assertEqual(integrate(t,f,'right'),[10,20,0])
    def test_duplicate_tick_rejected(self):
        with self.assertRaises(ValueError): integrate([0,0],[[0]*3,[1]*3],'trapezoid')
