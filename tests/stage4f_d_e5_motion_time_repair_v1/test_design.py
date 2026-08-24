import unittest
from coupling.stage4f_d_e5_motion_time_repair_v1.audit import run

class TestMotionTimeRepair(unittest.TestCase):
    def test_design_is_offline_and_fail_closed(self):
        value = run()
        self.assertEqual(value["mode"], "offline_only")
        self.assertEqual(value["real_matlab_openfoam_wsl_cfd_started"], 0)
        self.assertIn("derive target_time=current_time+dt for motion payload and OpenFOAM start", value["required_fix"])

if __name__ == "__main__":
    unittest.main()
