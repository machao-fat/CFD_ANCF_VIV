from __future__ import annotations

import unittest
import importlib.util
import struct
import tempfile
from pathlib import Path


class Stage354PreparationTests(unittest.TestCase):
    def test_fresh_runtime_wrapper(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage354_restart_boundary_v1/prepare_boundary_aligned_restart.py").read_text(encoding="utf-8")
        self.assertIn("stage354_restart_boundary_v1_fresh_candidate", text)
        self.assertIn("stage352_restart_boundary_v1/prepare_boundary_aligned_restart.py", text)

    def test_binary_list_with_semicolon_is_converted(self):
        root = Path(__file__).resolve().parents[2]
        source = root / "tools/stage352_restart_boundary_v1/prepare_boundary_aligned_restart.py"
        spec = importlib.util.spec_from_file_location("stage352_prepare_test", source)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        payload = struct.pack("<3d", 1.0, 2.0, 0.0)
        data = (b"FoamFile{}\n\nboundaryField\n{\n    cyl\n    {\n"
                b"        type fixedValue;\n"
                b"        value nonuniform List<vector> \n1\n(" + payload +
                b");\n    }\n}\n")
        with tempfile.TemporaryDirectory() as directory:
            field = Path(directory) / "pointDisplacement"
            field.write_bytes(data)
            result = module.patch_cylinder_value(field, (3.0, 4.0, 0.0))
            self.assertEqual(result["mode"], "nonuniform-to-uniform")
            self.assertIn(b"value           uniform (3 4 0);", field.read_bytes())


if __name__ == "__main__":
    unittest.main()
