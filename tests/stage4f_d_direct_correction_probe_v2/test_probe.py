import tempfile
import unittest
from pathlib import Path
from coupling.stage4f_d_direct_correction_probe_v2.probe import atomic_json


class ProbeTests(unittest.TestCase):
    def test_atomic_json_creates_parent_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "results" / "record.json"
            atomic_json(target, {"return_code": 0, "run_id": "x"})
            self.assertIn('"return_code": 0', target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
