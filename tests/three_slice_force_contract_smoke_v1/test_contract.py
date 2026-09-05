import unittest

from coupling.three_slice_force_contract_smoke_v1.contract import ContractError, bounded_midpoint_voronoi
from coupling.convergence_observability_v1.openfoam_log import OpenFOAMLogParser


class ContractTests(unittest.TestCase):
    def test_three_slice_partition_is_calculated_and_covers_fifty_metres(self):
        rows = bounded_midpoint_voronoi((8.333333333333334, 25.0, 41.666666666666664), (0.0, 50.0))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(abs(right-left-50.0/3.0) < 1e-12 for left, _, right in rows))
        self.assertAlmostEqual(sum(right-left for left, _, right in rows), 50.0)

    def test_rejects_implicit_or_unsorted_partition(self):
        with self.assertRaises(ContractError):
            bounded_midpoint_voronoi((25.0, 8.0, 41.0), (0.0, 50.0))

    def test_openfoam10_courant_before_time_header_is_not_shifted(self):
        parser = OpenFOAMLogParser()
        for line in (
            "Courant Number mean: 0.1 max: 0.2", "Time = 0.005s",
            "Solving for p, Initial residual = 1, Final residual = 1e-8, No Iterations 2",
            "time step continuity errors : sum local = 1e-9, global = 1e-10",
            "Courant Number mean: 0.1 max: 0.3", "Time = 0.01s",
            "Solving for p, Initial residual = 1, Final residual = 1e-8, No Iterations 2",
            "time step continuity errors : sum local = 1e-9, global = 1e-10",
        ):
            parser.feed(line)
        records = parser.finalize()
        self.assertEqual([record["courant_max"] for record in records], [0.2, 0.3])


if __name__ == "__main__":
    unittest.main()
