import tempfile
import unittest
from pathlib import Path

from coupling.stage4f_c_force_freshness_repair_v1 import ImmutableForceArtifact, ForceArtifactError


class ForceArtifactTests(unittest.TestCase):
    def test_snapshot_is_immutable_and_identity_bound(self):
        with tempfile.TemporaryDirectory(dir="D:/") as td:
            root = Path(td); source = root / "forces.dat"; target = root / "run" / "step" / "force.dat"
            source.write_text("1.52 (1 2 3) (4 5 6)\n", encoding="utf-8")
            item = ImmutableForceArtifact.create(source, target, run_id="R", case_id="C", step=5, slice_id=1, time_tick=1520000000)
            source.write_text("1.53 (9 9 9) (9 9 9)\n", encoding="utf-8")
            self.assertTrue(item.validate(run_id="R", case_id="C", step=5, slice_id=1, time_tick=1520000000)["immutable"])
            with self.assertRaises(ForceArtifactError): item.validate(run_id="R", case_id="C", step=6, slice_id=1, time_tick=1520000000)

    def test_overwrite_and_tamper_fail_closed(self):
        with tempfile.TemporaryDirectory(dir="D:/") as td:
            root = Path(td); source = root / "forces.dat"; target = root / "force.dat"; source.write_text("x", encoding="utf-8")
            item = ImmutableForceArtifact.create(source, target, run_id="R", case_id="C", step=0, slice_id=0, time_tick=1)
            with self.assertRaises(ForceArtifactError): ImmutableForceArtifact.create(source, target, run_id="R", case_id="C", step=0, slice_id=0, time_tick=1)
            target.write_text("tampered", encoding="utf-8")
            with self.assertRaises(ForceArtifactError): item.validate(run_id="R", case_id="C", step=0, slice_id=0, time_tick=1)


if __name__ == "__main__": unittest.main()
