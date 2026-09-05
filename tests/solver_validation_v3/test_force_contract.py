from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.multi_slice_mapping.mapping import (  # noqa: E402
    FORCE_TOLERANCE,
    SCHEMA_VERSION,
    SliceDefinition,
    SliceManifest,
    SchemaError,
    convert_openfoam_force,
    map_integrated_slice_forces,
)
from coupling.stage303_interface_mapping_repair_v1 import diagnose_mapping  # noqa: E402


class ForceContractV3Tests(unittest.TestCase):
    def test_openfoam_to_integrated_slice_formula(self) -> None:
        conversion = convert_openfoam_force((12.0, -6.0, 3.0), 2.0, 5.0)
        self.assertEqual(conversion.force_2d_Npm, (6.0, -3.0, 1.5))
        self.assertEqual(conversion.force_N, (30.0, -15.0, 7.5))

    def test_missing_span_is_fail_closed(self) -> None:
        with self.assertRaises(SchemaError):
            SliceDefinition.from_mapping({"slice_id": 0, "s_ref_m": 1.0, "slice_length_m": 2.0})

    def test_h_transpose_preserves_force_moment_and_virtual_work(self) -> None:
        manifest = SliceManifest(
            schema_version=SCHEMA_VERSION,
            case_id="v3-force-test",
            reference_length_m=50.0,
            represented_length_m=50.0,
            slices=(
                SliceDefinition(0, 8.333333333333334, 50.0 / 3.0, 1.0),
                SliceDefinition(1, 25.0, 50.0 / 3.0, 1.0),
                SliceDefinition(2, 41.666666666666664, 50.0 / 3.0, 1.0),
            ),
        )
        q = tuple(0.0 for _ in range(102))
        qdot = tuple((index % 7 - 3) * 0.01 for index in range(102))
        loads = ((1.0, 2.0, 0.0), (-1.5, 0.5, 0.0), (0.75, -1.0, 0.0))
        audit = diagnose_mapping(q, qdot, loads)
        self.assertLess(audit.force_balance_error, 1.0e-10)
        self.assertLess(audit.moment_balance_error, 1.0e-10)
        self.assertLess(audit.virtual_work_error, 1.0e-10)
        # The generic mapping has its own virtual-work audit; no length may be
        # applied after the loads have become integrated forces.
        H = {sid: ((1.0,), (0.0,), (0.0,)) for sid in range(3)}
        mapped = map_integrated_slice_forces(manifest, H, {sid: loads[sid] for sid in range(3)}, delta_q=(0.25,))
        self.assertIsNotNone(mapped.virtual_work)
        assert mapped.virtual_work is not None
        self.assertLess(mapped.virtual_work.error_rel, max(1.0e-10, FORCE_TOLERANCE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
