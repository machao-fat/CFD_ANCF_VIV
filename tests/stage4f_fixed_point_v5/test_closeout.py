import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_fixed_point_v5.closeout import _coefficient


class TestCloseoutContract(unittest.TestCase):
    def test_coefficient_parser_rejects_missing_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forceCoeffs.dat"
            path.write_text("# header\n1 0 2\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _coefficient(path, 2.0)
