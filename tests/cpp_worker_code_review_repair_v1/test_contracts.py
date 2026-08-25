import struct
import unittest

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelModel, EXTENDED_LAYOUT_MARKER


class CodeReviewRepairContractTests(unittest.TestCase):
    def test_default_boundary_and_mass_contract_are_serialized(self):
        model = KernelModel(elements=2, slices=3, slice_positions_m=(0.0, 5.0, 10.0),
                            fixed_dof=(0, 1, 2, 12, 13), prescribed_values=(0.0,) * 5)
        raw = model.bytes()
        fixed_count_offset = struct.calcsize("<13dii")
        marker, mass_order, fixed_count = struct.unpack_from("<Iii", raw, fixed_count_offset)
        self.assertEqual(marker, EXTENDED_LAYOUT_MARKER)
        self.assertEqual(mass_order, 5)
        self.assertEqual(fixed_count, 5)
        boundary_offset = fixed_count_offset + 12
        self.assertTrue(raw[boundary_offset:].startswith(b"ancf_v1_bottom_top_xy_zero\0"))

    def test_boundary_fields_fail_closed(self):
        model = KernelModel(elements=2, slices=3, fixed_dof=(0, 0), prescribed_values=(0.0, 0.0))
        with self.assertRaises(ValueError):
            model.bytes()

    def test_mass_quadrature_is_independent(self):
        model = KernelModel(elements=2, slices=3, mass_gauss_order=3)
        self.assertEqual(model.mass_gauss_order, 3)
        self.assertEqual(model.gauss_order, 3)
        self.assertNotEqual(model.bytes(), KernelModel(elements=2, slices=3, mass_gauss_order=5).bytes())


if __name__ == "__main__":
    unittest.main()
