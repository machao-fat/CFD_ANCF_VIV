import copy, unittest
from src.coupling.stage4f_c_limited_extension_v2.contract import build_contract, validate_contract

class Tests(unittest.TestCase):
    def test_frozen(self):
        c=build_contract(); validate_contract(c); self.assertEqual(c["continuous_blocks"], [[20,25],[25,30],[30,35],[35,40]]); self.assertEqual(c["end_tick_ns"],1532500000)
    def test_mutations_fail(self):
        for key,value in (("final_max_abs_Cd",11),("dt_tick_ns",1),("restart_parent_step",33)):
            c=copy.deepcopy(build_contract());c[key]=value
            with self.assertRaises(ValueError):validate_contract(c)
    def test_scope(self): self.assertIn("long_time_VIV",build_contract()["forbidden_scope"])

if __name__ == "__main__":unittest.main()
