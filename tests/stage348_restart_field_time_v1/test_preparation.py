from __future__ import annotations

import unittest
from pathlib import Path


class RestartFieldTimePreparationTests(unittest.TestCase):
    def test_contract_uses_mapping_time_not_directory_label(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage348_restart_field_time_v1/prepare_restart_field.py").read_text(encoding="utf-8")
        self.assertIn('"79.995"', text)
        self.assertIn('"required_uniform_time_index": 15999', text)
        self.assertIn('"openfoam_starts": 0', text)


if __name__ == "__main__":
    unittest.main()
