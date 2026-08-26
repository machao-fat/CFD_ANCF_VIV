from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from coupling.cpp_worker_confirm_v1.contracts import (
    CppConfirmContract, ContractError, REAL_AUTHORIZATION_TOKEN, load_source_checkpoint,
)
from coupling.cpp_worker_confirm_v1.real_coordinator import LaunchGuard


class ContractAndGuardTests(unittest.TestCase):
    def _contract(self, root: Path, *, allow: bool = False, authorization: str | None = None) -> CppConfirmContract:
        source = root / "source.json"; source.write_text('{"status":"committed"}\n', encoding="utf-8")
        return CppConfirmContract(
            stage_id="stage4f_d_cpp_worker_confirm_v1_real_001", run_id="cpp_confirm_real_001",
            case_id="cpp_confirm_real_case_001", runtime=root / "runtime", results=root / "results",
            source_checkpoint=source, source_checkpoint_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            allow_real_external_processes=allow, authorization=authorization,
        )

    def test_contract_is_bounded_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = self._contract(Path(directory))
            encoded = contract.to_dict()
            self.assertEqual(encoded["contract_sha256"], contract.to_dict()["contract_sha256"])
            self.assertEqual(encoded["slice_count"], 3)

    def test_real_launch_requires_explicit_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disabled = self._contract(root)
            with self.assertRaises(ContractError): LaunchGuard.require(disabled, REAL_AUTHORIZATION_TOKEN)
            enabled = self._contract(root, allow=True, authorization="wrong")
            with self.assertRaises(ContractError): LaunchGuard.require(enabled, "wrong")

    def test_c_drive_and_scope_expansion_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = self._contract(Path(directory))
            value = contract.to_dict(); value["scope"]["no_five_slice"] = False
            with self.assertRaises(ContractError):
                from coupling.cpp_worker_confirm_v1.contracts import validate_serialized_contract
                validate_serialized_contract(value, Path(directory))

    def test_real_coordinator_cannot_start_without_authorization(self) -> None:
        from coupling.cpp_worker_confirm_v1.real_coordinator import CppConfirmRun

        class Worker:
            def start(self): raise AssertionError("worker must not start")
            def stop(self): pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root)
            run = CppConfirmRun(contract, Worker(), lambda _sid, _path: None)
            with self.assertRaises(ContractError): run.start()

    def test_real_coordinator_requires_preflight_before_any_start(self) -> None:
        from coupling.cpp_worker_confirm_v1.real_coordinator import CppConfirmRun, CoordinatorError

        class Worker:
            def start(self): raise AssertionError("worker must not start")
            def stop(self): pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root, allow=True, authorization=REAL_AUTHORIZATION_TOKEN)
            run = CppConfirmRun(contract, Worker(), lambda _sid, _path: None,
                                authorization=REAL_AUTHORIZATION_TOKEN)
            with self.assertRaises(CoordinatorError): run.start()

    def test_legacy_mapping_response_requires_canonical_payload_audit(self) -> None:
        from coupling.cpp_worker_confirm_v1.real_coordinator import (
            CoordinatorError, _validate_generic_worker_response,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root)
            payload = {"q": [0.0], "qdot": [0.0], "qddot": [0.0], "residual": 0.0}
            encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            response = {
                "global_step": 560, "case_local_bridge_step": 1, "time_s": 2.20875,
                "integer_tick": 2208750000, "run_id": contract.run_id,
                "case_id": contract.case_id, "request_id": 1, "transaction_id": 2,
                "return_code": 0, "finite_value_audit": True, "sequence": 1, "ack": 1,
                "schema_version": 1, "producer": "cpp_ancf_worker", "consumer": "python_scheduler",
                "payload": payload, "payload_hash": hashlib.sha256(encoded).hexdigest(),
                "residual": 0.0, "iterations": 1,
            }
            _validate_generic_worker_response(response, contract=contract, global_step=560,
                                              time_s=2.20875, expected_bridge=1,
                                              expected_tick=2208750000)
            response["payload"] = {"q": [1.0]}
            with self.assertRaises(CoordinatorError):
                _validate_generic_worker_response(response, contract=contract, global_step=560,
                                                  time_s=2.20875, expected_bridge=1,
                                                  expected_tick=2208750000)

    def test_source_checkpoint_loader_is_explicit_utf8_and_hash_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            path.write_bytes('{"step":559,"time_s":2.2075}\n'.encode("utf-8"))
            value = load_source_checkpoint(path, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(value["step"], 559)
            with self.assertRaises(ContractError):
                load_source_checkpoint(path, "0" * 64)

    def test_real_motion_builder_rejects_missing_predictor_velocity(self) -> None:
        from coupling.cpp_worker_confirm_v1.real_coordinator import build_predictor_motion_by_slice, CoordinatorError
        from coupling.multi_slice_driver.contract import SliceSpec, build_slice_manifest
        from coupling.multi_slice_mapping.mapping import SliceManifest, ancf_hermite_H

        manifest = SliceManifest.from_mapping(build_slice_manifest(
            "case", [SliceSpec(0, 1.0, 1.0), SliceSpec(1, 2.0, 1.0), SliceSpec(2, 3.0, 1.0)]))
        prediction = {"global_step": 560, "time_s": 2.20875, "predictor": [0.0] * 24}
        H = {sid: ancf_hermite_H(float(sid + 1), (0.0, 1.5, 3.0), ndof=24) for sid in range(3)}
        refs = {sid: (0.0, 0.0, float(sid + 1)) for sid in range(3)}
        with self.assertRaises(CoordinatorError):
            build_predictor_motion_by_slice(prediction=prediction, manifest=manifest,
                H_by_slice_id=H, reference_positions_m=refs, global_step=560, time_s=2.20875)

    def test_real_motion_builder_uses_predictor_state_for_all_slices(self) -> None:
        from coupling.cpp_worker_confirm_v1.real_coordinator import build_predictor_motion_by_slice
        from coupling.multi_slice_driver.contract import SliceSpec, build_slice_manifest
        from coupling.multi_slice_mapping.mapping import SliceManifest, ancf_hermite_H

        manifest = SliceManifest.from_mapping(build_slice_manifest(
            "case", [SliceSpec(0, 1.0, 1.0), SliceSpec(1, 2.0, 1.0), SliceSpec(2, 3.0, 1.0)]))
        prediction = {"global_step": 560, "case_local_bridge_step": 1, "time_s": 2.20875,
                      "integer_tick": 2208750000, "run_id": "run", "case_id": "case",
                      "predictor": [0.0] * 24, "predictor_qdot": [0.0] * 24,
                      "predictor_qddot": [0.0] * 24}
        H = {sid: ancf_hermite_H(float(sid + 1), (0.0, 1.5, 3.0), ndof=24) for sid in range(3)}
        refs = {sid: (0.0, 0.0, float(sid + 1)) for sid in range(3)}
        motions = build_predictor_motion_by_slice(prediction=prediction, manifest=manifest,
            H_by_slice_id=H, reference_positions_m=refs, global_step=560, time_s=2.20875)
        self.assertEqual(set(motions), {0, 1, 2})
        self.assertTrue(all(item.step == 560 and item.time_s == 2.20875 for item in motions.values()))

    def test_real_motion_builder_rejects_identity_and_finite_value_mutations(self) -> None:
        from coupling.cpp_worker_confirm_v1.real_coordinator import build_predictor_motion_by_slice, CoordinatorError
        from coupling.multi_slice_driver.contract import SliceSpec, build_slice_manifest
        from coupling.multi_slice_mapping.mapping import SliceManifest, ancf_hermite_H

        manifest = SliceManifest.from_mapping(build_slice_manifest(
            "case", [SliceSpec(0, 1.0, 1.0), SliceSpec(1, 2.0, 1.0), SliceSpec(2, 3.0, 1.0)]))
        base = {"global_step": 560, "case_local_bridge_step": 1, "time_s": 2.20875,
                "integer_tick": 2208750000, "run_id": "run", "case_id": "case",
                "predictor": [0.0] * 24, "predictor_qdot": [0.0] * 24,
                "predictor_qddot": [0.0] * 24}
        H = {sid: ancf_hermite_H(float(sid + 1), (0.0, 1.5, 3.0), ndof=24) for sid in range(3)}
        refs = {sid: (0.0, 0.0, float(sid + 1)) for sid in range(3)}
        for mutation in (
            {"case_local_bridge_step": 2}, {"integer_tick": 2208750001},
            {"case_id": "other"}, {"predictor": [float("nan")] * 24},
        ):
            prediction = dict(base); prediction.update(mutation)
            with self.assertRaises(CoordinatorError):
                build_predictor_motion_by_slice(prediction=prediction, manifest=manifest,
                    H_by_slice_id=H, reference_positions_m=refs, global_step=560, time_s=2.20875,
                    expected_run_id="run")


if __name__ == "__main__": unittest.main()
