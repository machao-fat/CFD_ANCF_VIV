from __future__ import annotations

import unittest

from src.coupling.online_file_coupling.continuous_fsi_driver import (
    _project_structure_load,
)


class TransverseLoadProjectionTests(unittest.TestCase):
    def test_full_mode_preserves_ancf_components(self) -> None:
        raw = [[11.0, -7.0, 3.0]]
        self.assertEqual(
            _project_structure_load(raw, branch="ancf", load_mode="full"), raw
        )
        self.assertEqual(raw, [[11.0, -7.0, 3.0]])

    def test_full_mode_retains_historical_eb_axial_projection(self) -> None:
        self.assertEqual(
            _project_structure_load(
                [[11.0, -7.0, 3.0]], branch="eb", load_mode="full"
            ),
            [[11.0, -7.0, 0.0]],
        )

    def test_transverse_mode_is_identical_for_both_branches(self) -> None:
        raw = [[11.0, -7.0, 3.0], [-2.0, 5.0, 9.0]]
        expected = [[0.0, -7.0, 0.0], [0.0, 5.0, 0.0]]
        for branch in ("eb", "ancf"):
            self.assertEqual(
                _project_structure_load(
                    raw, branch=branch, load_mode="transverse_only"
                ),
                expected,
            )
        self.assertEqual(raw, [[11.0, -7.0, 3.0], [-2.0, 5.0, 9.0]])

    def test_unknown_mode_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            _project_structure_load([[1.0, 2.0, 3.0]], branch="ancf", load_mode="typo")


if __name__ == "__main__":
    unittest.main()
