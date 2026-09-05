import unittest

from coupling.three_slice_force_contract_smoke_v1.contract import ContractError, bounded_midpoint_voronoi


class ContractTests(unittest.TestCase):
    def test_three_slice_partition_is_calculated_and_covers_fifty_metres(self):
        rows = bounded_midpoint_voronoi((8.333333333333334, 25.0, 41.666666666666664), (0.0, 50.0))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(abs(right-left-50.0/3.0) < 1e-12 for left, _, right in rows))
        self.assertAlmostEqual(sum(right-left for left, _, right in rows), 50.0)

    def test_rejects_implicit_or_unsorted_partition(self):
        with self.assertRaises(ContractError):
            bounded_midpoint_voronoi((25.0, 8.0, 41.0), (0.0, 50.0))


if __name__ == "__main__":
    unittest.main()
