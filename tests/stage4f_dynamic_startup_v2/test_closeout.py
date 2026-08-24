import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_dynamic_startup_v2.closeout import closeout


class TestCloseout(unittest.TestCase):
    def test_unbalanced_drag_blocks_restart_and_preserves_single_length_factor(self):
        with tempfile.TemporaryDirectory() as raw:
            run = Path(raw) / "run"; result = Path(raw) / "result"; (run / "exchange" / "slice_0000" / "load").mkdir(parents=True)
            (run / "real_run_summary.json").write_text(json.dumps({"checkpoint_audit":[{"valid":True}]}), encoding="utf-8")
            (run / "dynamic_hot_start_audit.json").write_text(json.dumps({"force_scale_passed":True,"hot_start":{"steps":[{"Cd":3.6}],"max_cfl":.2}}), encoding="utf-8")
            keys = ["step","slice_id","time_s","openfoam_force_x_N","force_x_N","slice_length_m"]
            with (run / "exchange" / "slice_0000" / "load" / "load_step00000002_iter0000.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=keys); writer.writeheader(); writer.writerow({"step":2,"slice_id":0,"time_s":.0575,"openfoam_force_x_N":6000,"force_x_N":100000,"slice_length_m":50/3})
            gate = closeout(run, result)
            self.assertFalse(gate["final_force_scale_passed"])
            self.assertFalse(gate["restart_authorized"])
            self.assertEqual(gate["coupled_force_audit"][0]["slices"][0]["single_length_factor"], 50/3)

