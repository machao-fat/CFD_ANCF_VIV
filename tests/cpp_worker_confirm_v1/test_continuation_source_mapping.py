"""Offline guards for the step599 -> step600 continuation boundary."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from coupling.cpp_worker_confirm_v1.contracts import CppConfirmContract, ContractError
from coupling.cpp_worker_persistent_ipc_v1.mapping_contract import SourceMapping
from tools.cpp_worker_confirm_v1.run_authorized_confirm_001 import _restart_payload_from_source


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "cases/openfoam/cpp_worker_persistent_ipc_v1/continuation_source_step00000599_v1.json"
TEMPLATE = ROOT / "cases/openfoam/cpp_worker_persistent_ipc_v1/continuation_template_014"
MOTION_TEMPLATE = ROOT / "cases/openfoam/cpp_worker_persistent_ipc_v1/continuation_template_016"


class ContinuationSourceMappingTests(unittest.TestCase):
    def test_source599_contract_and_first_target(self) -> None:
        raw = SOURCE.read_bytes()
        value = json.loads(raw.decode("utf-8"))
        self.assertEqual(value["status"], "committed")
        self.assertEqual(value["step"], 599)
        self.assertEqual(value["time_s"], 2.2575)
        self.assertEqual(value["time_tick"], 2_257_500_000)
        contract = CppConfirmContract(
            stage_id="offline_stage198", run_id="offline_run198", case_id="offline_case198",
            runtime=ROOT / "runtime/cpp_worker_persistent_ipc_v1/offline_198",
            results=ROOT / "results/198_offline_contract", source_checkpoint=SOURCE,
            source_checkpoint_sha256=hashlib.sha256(raw).hexdigest(),
            source_global_step=599, source_time_s=2.2575, source_tick=2_257_500_000,
        )
        contract.validate(ROOT)
        mapping = SourceMapping(599, 2.2575, 2_257_500_000, 0.00125)
        self.assertEqual(mapping.target(global_step=600, case_local_bridge_step=1,
                                       time_s=2.25875, integer_tick=2_258_750_000), (1, 2_258_750_000))

    def test_source_time_or_tick_mismatch_fails_closed(self) -> None:
        raw = SOURCE.read_bytes()
        kwargs = dict(
            stage_id="offline_stage198", run_id="offline_run198b", case_id="offline_case198b",
            runtime=ROOT / "runtime/cpp_worker_persistent_ipc_v1/offline_198b",
            results=ROOT / "results/198_offline_contract_b", source_checkpoint=SOURCE,
            source_checkpoint_sha256=hashlib.sha256(raw).hexdigest(), source_global_step=599,
            source_time_s=2.25875, source_tick=2_258_750_000,
        )
        with self.assertRaises(ContractError):
            CppConfirmContract(**kwargs).validate(ROOT)

    def test_continuation_template_has_matching_cfd_clock(self) -> None:
        for sid in range(3):
            control = (TEMPLATE / f"slice_{sid:04d}" / "system" / "controlDict").read_text(encoding="utf-8")
            config = json.loads((TEMPLATE / f"slice_{sid:04d}" / "multi_slice_case_config.json").read_text(encoding="utf-8"))
            self.assertIn("startTime       2.2575;", control)
            self.assertIn("endTime         2.3075;", control)
            self.assertEqual(config["start_time_s"], 2.2575)
            self.assertEqual(config["end_time_s"], 2.3075)

    def test_motion_reader_restart_clock_matches_source(self) -> None:
        for sid in range(3):
            text = (MOTION_TEMPLATE / f"slice_{sid:04d}" / "constant" / "dynamicMeshDict").read_text(encoding="utf-8")
            self.assertIn("startTime       2.2575;", text)
            self.assertIn("couplingDeltaT  0.00125;", text)

    def test_runner_creates_fresh_consumed_namespace(self) -> None:
        runner = (ROOT / "tools/cpp_worker_confirm_v1/run_authorized_confirm_001.py").read_text(encoding="utf-8")
        self.assertIn('(destination / "coupling" / "consumed").mkdir', runner)
        self.assertIn("exist_ok=False", runner)

    def test_portable_barrier_source_uses_committed_next_load(self) -> None:
        structure = {"q": [1.0], "qdot": [2.0], "qddot": [3.0]}
        source = {"committed": True, "checkpoint_metadata": {"ancf_restart_state": {
            "structure": structure,
            "applied_slice_forces_N": [[1.0, 1.0, 1.0]] * 3,
            "next_applied_slice_forces_N": [[2.0, 2.0, 2.0]] * 3,
        }}}
        payload, loads = _restart_payload_from_source(source)
        self.assertEqual(payload["structure"], structure)
        self.assertEqual(loads, [[2.0, 2.0, 2.0]] * 3)
        with self.assertRaises(RuntimeError):
            _restart_payload_from_source({"checkpoint_metadata": {"ancf_restart_state": {
                "structure": structure, "next_applied_slice_forces_N": [[float("nan"), 0.0, 0.0]] * 3,
            }}})


if __name__ == "__main__":
    unittest.main()
