from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.stage303_interface_mapping_repair_v1 import (  # noqa: E402
    DEFAULT_ELEMENTS,
    DEFAULT_SLICE_POSITIONS_M,
    canonical_h_row,
    diagnose_mapping,
    project_interface,
)
from coupling.stage303_interface_mapping_repair_v1.canonical_projection import MappingError  # noqa: E402


class ProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.q = [0.0] * (6 * (DEFAULT_ELEMENTS + 1))
        self.qdot = [0.0] * len(self.q)
        for node in range(DEFAULT_ELEMENTS + 1):
            base = 6 * node
            self.q[base + 2] = node * 50.0 / DEFAULT_ELEMENTS
            self.q[base + 1] = 0.001 * node
            self.q[base + 5] = 1.0
            self.qdot[base + 1] = 0.001 * node * (50.0 / DEFAULT_ELEMENTS)
            self.qdot[base + 4] = 0.001

    def test_projection_is_worker_H_not_legacy_first_nodes(self):
        _, velocity, positions, _ = project_interface(self.q, self.qdot)
        self.assertTrue(math.isfinite(positions[0][1]))
        self.assertAlmostEqual(velocity[0][1], 0.001 * DEFAULT_SLICE_POSITIONS_M[0], places=12)
        self.assertNotEqual(self.q[1], positions[0][1])
        self.assertEqual(len(canonical_h_row(DEFAULT_SLICE_POSITIONS_M[0])), len(self.q))

    def test_virtual_work_force_and_moment_are_zero_for_canonical_mapping(self):
        forces = ((0.3, -0.2, 0.0), (-0.1, 0.4, 0.0), (0.2, 0.1, 0.0))
        audit = diagnose_mapping(self.q, self.qdot, forces)
        self.assertLess(audit.virtual_work_error, 1.0e-12)
        self.assertLess(audit.force_balance_error, 1.0e-12)
        self.assertLess(audit.moment_balance_error, 1.0e-12)

    def test_identity_and_finite_guard(self):
        bad = list(self.qdot)
        bad[1] = math.inf
        with self.assertRaises(ValueError):
            project_interface(self.q, bad)

    def test_out_of_case_slice_is_rejected(self):
        with self.assertRaises(MappingError):
            project_interface(self.q, self.qdot, slice_positions_m=(51.0, 25.0, 41.0))

    def test_force_dimension_and_nonfinite_are_rejected(self):
        with self.assertRaises(MappingError):
            diagnose_mapping(self.q, self.qdot, ((1.0, 0.0, 0.0),))
        with self.assertRaises(MappingError):
            diagnose_mapping(self.q, self.qdot, ((math.nan, 0.0, 0.0),) * 3)


if __name__ == "__main__":
    unittest.main()
