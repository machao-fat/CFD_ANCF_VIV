from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from coupling.cpp_worker_confirm_v1.barrier import Stage100SliceBarrier
from coupling.cpp_worker_confirm_v1.envelope import MotionEnvelope, load_envelope, payload_hash
from coupling.cpp_worker_confirm_v1.real_coordinator import CoordinatorError, _validate_generic_worker_response
from coupling.multi_slice_driver.contract import SliceSpec, build_slice_manifest
from coupling.multi_slice_mapping.mapping import LoadRecord, MotionRecord, RuntimeConfig, SliceManifest
from coupling.performance_optimization_v2.coordinator import SliceResult, StepIdentity, canonical_hash


def _identity() -> StepIdentity:
    return StepIdentity.create(run_id="run", case_id="case", source_global_step=559,
                               source_time_s=2.2075, source_tick=2207500000,
                               global_step=560, time_s=2.20875, dt_s=0.00125)


def _motion() -> MotionRecord:
    return MotionRecord(schema_version="0.2.1", case_id="case", step=560, coupling_iteration=0,
        time_s=2.20875, slice_id=0, s_ref_m=1.0, slice_length_m=1.0,
        x_ref_m=0.0, y_ref_m=0.0, z_ref_m=1.0, ux_m=0.0, uy_m=0.0, uz_m=0.0,
        x_m=0.0, y_m=0.0, z_m=1.0, vx_mps=0.0, vy_mps=0.0, vz_mps=0.0,
        ax_mps2=0.0, ay_mps2=0.0, az_mps2=0.0)


class EnvelopeAndRecoveryTests(unittest.TestCase):
    def test_envelope_is_deterministic_and_binds_load_identity(self):
        identity = _identity(); motion = _motion()
        envelope = MotionEnvelope.create(identity=identity, motion=motion,
                                         upstream_request_id=1, upstream_transaction_id=2,
                                         upstream_sequence=1)
        manifest = SliceManifest.from_mapping(build_slice_manifest("case", [SliceSpec(0, 1.0, 1.0)]))
        load = LoadRecord.from_conversion(case_id="case", step=560, time_s=2.20875,
            slice_definition=manifest.slices[0], unit_span_m=1.0,
            openfoam_force_N=(1.0, 2.0, 0.0), cfd_time_step_s=0.00125).to_dict()
        result = load_envelope(identity=identity, slice_id=0, load=load, motion=envelope)
        self.assertEqual(result["payload_sha256"], payload_hash(load))
        bad = dict(load); bad["step"] = 559
        with self.assertRaises(CoordinatorError):
            load_envelope(identity=identity, slice_id=0, load=bad, motion=envelope)
        bad_motion = MotionEnvelope(**{**envelope.__dict__, "payload_sha256": "0" * 64})
        with self.assertRaises(CoordinatorError):
            load_envelope(identity=identity, slice_id=0, load=load, motion=bad_motion)

    def test_unresolved_commit_journal_blocks_start_before_engines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); journal = root / "commit_journal"; journal.mkdir()
            (journal / "commit_00000560.json").write_text(json.dumps({
                "schema_version": "stage100_commit_journal_v1", "state": "prepared"}) + "\n",
                encoding="utf-8")
            starts = []
            class Engine:
                def start(self): starts.append(1)
                def stop(self): pass
            barrier = Stage100SliceBarrier(run_id="run", case_id="case", source_global_step=559,
                source_time_s=2.2075, source_tick=2207500000, dt_s=0.00125,
                runtime=root, engine_factory=lambda _sid, _path: Engine())
            with self.assertRaises(CoordinatorError): barrier.start()
            self.assertEqual(starts, [])

    def test_generic_worker_response_rejects_identity_and_negative_residual(self):
        payload = {"q": [0.0]}
        encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True,
                              separators=(",", ":"), allow_nan=False) + "\n").encode()
        response = {"global_step": 560, "case_local_bridge_step": 1, "time_s": 2.20875,
            "integer_tick": 2208750000, "run_id": "run", "case_id": "case",
            "request_id": 1, "transaction_id": 2, "return_code": 0,
            "finite_value_audit": True, "sequence": 1, "ack": 1,
            "schema_version": 1, "producer": "cpp_ancf_worker", "consumer": "python_scheduler",
            "payload": payload, "payload_hash": hashlib.sha256(encoded).hexdigest(),
            "residual": 0.0, "iterations": 1}
        class Contract:
            run_id = "run"; case_id = "case"
        _validate_generic_worker_response(response, contract=Contract(), global_step=560,
                                          time_s=2.20875, expected_bridge=1, expected_tick=2208750000)
        response["residual"] = -1.0
        with self.assertRaises(CoordinatorError):
            _validate_generic_worker_response(response, contract=Contract(), global_step=560,
                                              time_s=2.20875, expected_bridge=1, expected_tick=2208750000)


if __name__ == "__main__":
    unittest.main()
