import copy
import unittest
from pathlib import Path

from src.coupling.stage4f_three_slice_timestep_diagnostic_v2.audit import audit_branch, audit_step, final_gate
from src.coupling.stage4f_three_slice_timestep_diagnostic_v2.contract import build_contract, validate_contract
from src.coupling.stage4f_three_slice_timestep_diagnostic_v2.execute import branch_plan, execute_diagnostic, process_record_complete
from src.coupling.stage4f_three_slice_timestep_diagnostic_v2.v2_engine import factory


def step(i=0, branch="D1"):
    dt = .00125 if branch == "D1" else .000625
    return {"step": i, "time_s": 1.5075+(i+1)*dt, "slices": [{"slice_id": x} for x in range(3)],
            "force_observation_unique": True, "state_role": "committed", "geometry_state_role": "predictor",
            "max_cfl": .2, "virtual_work_relative_error": 1e-16, "force_conversion_relative_error": 0,
            "mesh_center_motion_error_m": 1e-16, "position_difference_over_D": 1e-6,
            "max_abs_Cd": 2, "velocity_difference_over_U": .001, "log_passed": True,
            "checkpoint_passed": True, "process_evidence_passed": True}


class TestDiagnosticV2(unittest.TestCase):
    def test_01_d1_plan(self): self.assertEqual(branch_plan("D1", Path("r"), Path("p"))["steps"], 6)
    def test_02_d2_plan(self): self.assertEqual(branch_plan("D2", Path("r"), Path("p"))["steps"], 12)
    def test_03_d1_dt(self): self.assertEqual(branch_plan("D1", Path("r"), Path("p"))["dt_s"], .00125)
    def test_04_d2_dt(self): self.assertEqual(branch_plan("D2", Path("r"), Path("p"))["dt_s"], .000625)
    def test_05_end_time(self): self.assertEqual(branch_plan("D2", Path("r"), Path("p"))["end_time_s"], 1.515)
    def test_06_contract_hash(self): validate_contract(build_contract("p", "h", "c"))
    def test_07_contract_tamper(self):
        c=build_contract("p","h","c"); c["thresholds"]["abs_cd_max"]=11
        with self.assertRaises(ValueError): validate_contract(c)
    def test_08_missing_slice(self):
        r=step(); r["slices"].pop(); self.assertIn("slice_identity", audit_step(r,branch="D1",expected_step=0)["blocking_failures"])
    def test_09_duplicate_slice(self):
        r=step(); r["slices"][1]["slice_id"]=0; self.assertFalse(audit_step(r,branch="D1",expected_step=0)["diagnostic_continuation_allowed"])
    def test_10_old_force(self):
        r=step(); r["force_observation_unique"]=False; self.assertIn("force_observation_identity",audit_step(r,branch="D1",expected_step=0)["failures"])
    def test_11_duplicate_force_line(self):
        r=step(); r["force_observation_unique"]=False; self.assertTrue(audit_step(r,branch="D1",expected_step=0)["blocking_failures"])
    def test_12_time_shift(self):
        r=step(); r["time_s"]+=.001; self.assertIn("time_alignment",audit_step(r,branch="D1",expected_step=0)["failures"])
    def test_13_state_role(self):
        r=step(); r["state_role"]="predictor"; self.assertIn("state_role",audit_step(r,branch="D1",expected_step=0)["failures"])
    def test_14_cd_boundary(self):
        r=step(); r["max_abs_Cd"]=10; self.assertNotIn("abs_cd",audit_step(r,branch="D1",expected_step=0)["failures"])
    def test_15_cd_over(self):
        r=step(); r["max_abs_Cd"]=10.0001; self.assertTrue(audit_step(r,branch="D1",expected_step=0)["diagnostic_continuation_allowed"])
    def test_16_velocity_boundary(self):
        r=step(); r["velocity_difference_over_U"]=.01; self.assertNotIn("velocity_consistency",audit_step(r,branch="D1",expected_step=0)["failures"])
    def test_17_cfl_strict(self):
        r=step(); r["max_cfl"]=.8; self.assertIn("cfl",audit_step(r,branch="D1",expected_step=0)["blocking_failures"])
    def test_18_virtual_work(self):
        r=step(); r["virtual_work_relative_error"]=1.1e-12; self.assertIn("virtual_work",audit_step(r,branch="D1",expected_step=0)["failures"])
    def test_19_force_conversion(self):
        r=step(); r["force_conversion_relative_error"]=1.1e-10; self.assertIn("force_conversion",audit_step(r,branch="D1",expected_step=0)["failures"])
    def test_20_checkpoint(self):
        r=step(); r["checkpoint_passed"]=False; self.assertIn("checkpoint",audit_step(r,branch="D1",expected_step=0)["failures"])
    def test_21_pid_evidence(self): self.assertFalse(process_record_complete({"pid":1,"creation_time":2}))
    def test_22_d1_authorizes_d2_on_cd_only(self):
        rows=[step(i) for i in range(6)]; rows[2]["max_abs_Cd"]=11; self.assertTrue(audit_branch("D1",rows)["D2_authorized"])
    def test_23_repair2_pattern_replay(self):
        rows=[step(i) for i in range(6)]; rows[2].update(max_abs_Cd=11.003110867115256,velocity_difference_over_U=.01873367971574207)
        a=audit_branch("D1",rows); self.assertTrue(a["D2_authorized"]); self.assertFalse(a["passed"])
    def test_24_log_fatal_blocks(self):
        r=step(); r["log_passed"]=False; self.assertIn("log",audit_step(r,branch="D1",expected_step=0)["blocking_failures"])
    def test_gate_accept(self):
        d1=audit_branch("D1",[step(i) for i in range(6)]); d2=audit_branch("D2",[step(i,"D2") for i in range(12)])
        self.assertEqual(final_gate(d1,d2)["terminal_state"],"accepted_timestep_refinement_candidate")
    def test_gate_refinement_not_sufficient(self):
        d1=audit_branch("D1",[step(i) for i in range(6)]); rows=[step(i,"D2") for i in range(12)]; rows[-1]["max_abs_Cd"]=10.1
        self.assertEqual(final_gate(d1,audit_branch("D2",rows))["terminal_state"],"failure_timestep_refinement_not_sufficient")
    def test_serial_executor_stops_non_tolerated_failure_and_shuts_down(self):
        closed=[]
        def run(i, target):
            row=step(i); row["time_s"]=target
            if i == 1: row["log_passed"]=False
            return row
        result=execute_diagnostic("D1",run,lambda: closed.append(True))
        self.assertEqual(result["steps_completed"],2); self.assertEqual(closed,[True])
    def test_real_engine_factory_is_exposed(self): self.assertTrue(callable(factory))

if __name__ == "__main__": unittest.main()
