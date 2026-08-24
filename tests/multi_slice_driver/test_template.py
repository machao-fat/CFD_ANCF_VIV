from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TemplateGenerationTests(unittest.TestCase):
    def test_parameterized_case_renders_independent_paths_and_stage3_mover(self):
        project = Path(__file__).resolve().parents[2]
        generator = project / "cases" / "openfoam" / "multi_slice_template" / "generate_case.py"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            reference = root / "reference"
            (reference / "constant").mkdir(parents=True)
            (reference / "system").mkdir(parents=True)
            (reference / "constant" / "reference_marker").write_text("unchanged\n", encoding="utf-8")
            output = root / "slice_0003"
            command = [
                sys.executable, str(generator), "--output", str(output), "--reference-case", str(reference),
                "--case-id", "demo_0003", "--slice-id", "3", "--s-ref-m", "0.75",
                "--slice-length-m", "0.25", "--unit-span-m", "1", "--start-time", "0",
                "--end-time", "0.005", "--delta-t", "0.0025", "--exchange-dir", "exchange_3",
                "--motion-input", "exchange_3/motion.csv", "--load-output", "postProcessing/forces_3",
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("interpolatingSolidBody", (output / "constant" / "dynamicMeshDict").read_text(encoding="utf-8"))
            dynamic = (output / "constant" / "dynamicMeshDict").read_text(encoding="utf-8")
            self.assertIn("sliceId         3", dynamic)
            self.assertIn("exchange_3/motion.csv", dynamic)
            control = (output / "system" / "controlDict").read_text(encoding="utf-8")
            self.assertIn("endTime         0.005", control)
            self.assertTrue((output / "exchange_3" / "consumed").is_dir())
            self.assertTrue((output / "postProcessing" / "forces_3").is_dir())
            config = json.loads((output / "multi_slice_case_config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["slice_id"], 3)
            self.assertEqual(config["slice_length_m"], 0.25)


if __name__ == "__main__":
    unittest.main()

