from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "coupling"))
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_comprehensive_audit_repair_v1.mapping_contract import (
    DEFAULT_STEP559_MAPPING,
    SourceMapping,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import FrameError


class MappingContractTests(unittest.TestCase):
    def test_step559_to_560_is_canonical(self) -> None:
        DEFAULT_STEP559_MAPPING.target(
            global_step=560, case_local_bridge_step=1,
            time_s=2.20875, integer_tick=2208750000)

    def test_first_frame_source_mapping_is_explicit(self) -> None:
        with self.assertRaises(FrameError):
            DEFAULT_STEP559_MAPPING.target(
                global_step=560, case_local_bridge_step=2,
                time_s=2.20875, integer_tick=2208750000)

    def test_current_time_and_tick_mismatch_fail_closed(self) -> None:
        for kwargs in (
            dict(global_step=560, case_local_bridge_step=1, time_s=2.2075, integer_tick=2207500000),
            dict(global_step=560, case_local_bridge_step=1, time_s=2.20875, integer_tick=2207500001),
            dict(global_step=561, case_local_bridge_step=1, time_s=2.20875, integer_tick=2208750000),
        ):
            with self.assertRaises(FrameError):
                DEFAULT_STEP559_MAPPING.target(**kwargs)

    def test_invalid_source_contract_is_rejected(self) -> None:
        with self.assertRaises(FrameError):
            SourceMapping(559, 2.2075, 2207500001, 0.00125)


if __name__ == "__main__":
    unittest.main()
