from __future__ import annotations

import io
import hashlib
import json
import os
import struct
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    HEADER as KERNEL_HEADER,
    KernelModel,
    KernelStepRequest,
    decode_kernel_response,
    encode_kernel_request,
    validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    FrameError,
    HEADER,
    RESPONSE,
    StepRequest,
    decode_response,
)
from coupling.cpp_worker_persistent_ipc_v1.worker_client import PersistentCppWorkerClient
from coupling.cpp_worker_confirm_v1.cpp_adapter import CppAdapterError, CppKernelCampaignAdapter


ROOT = Path(__file__).resolve().parents[2]
_BUILD_ROOT = Path(os.environ.get(
    "CFD_ANCF_STAGE_BUILD",
    str(ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "build-release"),
))
WORKER = _BUILD_ROOT / "Release" / "cfd_ancf_ancf_kernel_worker.exe"


def _transport_request() -> StepRequest:
    return StepRequest(
        sequence=1, global_step=560, case_local_bridge_step=1,
        integer_tick=2_208_750_000, time_s=2.20875, dt_s=0.00125,
        request_id=1, transaction_id=2, run_id="run", case_id="case",
        q=(0.0,), qdot=(0.0,), force=(0.0,),
    )


def _kernel_request(sequence: int, global_step: int, bridge: int, time_s: float, tick: int) -> KernelStepRequest:
    model = KernelModel(
        length_m=10.0, diameter_m=1.0, inner_diameter_m=0.9,
        elements=2, slices=3, top_tension_N=0.0, newton_tolerance=1.0e-4,
        slice_positions_m=(0.0, 5.0, 10.0),
    )
    q = [0.0] * model.ndof
    for node in range(model.elements + 1):
        q[6 * node + 2] = node * model.length_m / model.elements
        q[6 * node + 5] = 1.0
    return KernelStepRequest(
        sequence=sequence, global_step=global_step, case_local_bridge_step=bridge,
        integer_tick=tick, time_s=time_s, dt_s=0.00125,
        request_id=1000 + sequence, transaction_id=2000 + sequence,
        run_id="pair_lineage_run", case_id="pair_lineage_case", model=model,
        q=tuple(q), qdot=(0.0,) * model.ndof, qddot=(0.0,) * model.ndof,
        base_load=(0.0,) * model.ndof, slice_force=(0.0,) * (3 * model.slices),
    )


class ProtocolLifecycleAndPairLineageTests(unittest.TestCase):
    def test_kernel_model_rejects_unrepresentable_physics_switches(self) -> None:
        value = _kernel_request(1, 560, 1, 2.20875, 2_208_750_000)
        with self.assertRaises(FrameError):
            replace(value, model=replace(value.model, include_gravity=False)).payload()
        with self.assertRaises(FrameError):
            replace(value, model=replace(value.model, top_tension_N="2000")).payload()

    @unittest.skipUnless(WORKER.is_file(), "Stage-local C++ kernel worker has not been built")
    def test_kernel_worker_input_eof_without_shutdown_is_fail_closed(self) -> None:
        process = subprocess.Popen(
            [str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0,
        )
        assert process.stdin is not None
        try:
            process.stdin.close()
            process.wait(timeout=10)
            self.assertEqual(process.returncode, 22)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            if process.stdout is not None and not process.stdout.closed:
                process.stdout.close()
            if process.stderr is not None and not process.stderr.closed:
                process.stderr.close()

    def test_kernel_request_rejects_non_numeric_state_and_identity_controls(self) -> None:
        value = _kernel_request(1, 560, 1, 2.20875, 2_208_750_000)
        with self.assertRaises(FrameError):
            replace(value, q=("0",) + value.q[1:]).payload()
        with self.assertRaises(FrameError):
            replace(value, run_id="run\0replay").payload()
        with self.assertRaises(FrameError):
            replace(value, time_s=1.0e10, integer_tick=10_000_000_000_000_000_000).payload()

    def test_dual_record_rejects_boolean_identity_and_state_values(self) -> None:
        from coupling.cpp_worker_persistent_ipc_v1.dual_run import DualStepRecord
        raw = _kernel_request(1, 560, 1, 2.20875, 2_208_750_000)
        base = {"run_id": "r", "case_id": "c", "global_step": 560,
                "case_local_bridge_step": 1, "time_s": 2.20875,
                "integer_tick": 2_208_750_000}
        base.update({name: [0.0] for name in ("q", "qdot", "qddot", "internal_force",
                                               "external_force", "generalized_force",
                                               "predictor", "corrector", "residual")})
        with self.assertRaises(FrameError):
            DualStepRecord.from_mapping({**base, "global_step": True})
        with self.assertRaises(FrameError):
            DualStepRecord.from_mapping({**base, "q": [True]})

    def _adapter(self) -> CppKernelCampaignAdapter:
        class Worker:
            def start(self): pass
            def stop(self): pass
            def step(self, request):
                zeros = (0.0,) * len(request.q)
                arrays = tuple(request.q) + tuple(request.qdot) + tuple(request.qddot) + zeros * 4 + tuple(request.q)
                return SimpleNamespace(
                    sequence=request.sequence, global_step=request.global_step,
                    case_local_bridge_step=request.case_local_bridge_step,
                    integer_tick=request.integer_tick, time_s=request.time_s,
                    request_id=request.request_id, transaction_id=request.transaction_id,
                    run_id=request.run_id, case_id=request.case_id, ack=1,
                    return_code=0, finite_value_audit=True, q=request.q,
                    qdot=request.qdot, qddot=request.qddot,
                    internal_force=zeros, external_force=zeros, generalized_force=zeros,
                    predictor=zeros, corrector=request.q, residual=0.0, iterations=1,
                    payload_hash=hashlib.sha256(struct.pack("<" + "d" * len(arrays), *arrays)).digest(),
                )
        return CppKernelCampaignAdapter(
            worker=Worker(), model=object(), request_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            run_id="checkpoint_run", case_id="checkpoint_case", source_global_step=559,
            source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
            q=(0.0, 0.0, 0.0), qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0),
            base_load=(0.0, 0.0, 0.0), slice_count=3,
        )

    def test_client_requires_initialize_and_becomes_terminal_after_disconnect(self) -> None:
        reader = io.BytesIO()
        writer = io.BytesIO()
        client = PersistentCppWorkerClient(reader, writer)
        with self.assertRaises(FrameError):
            client.request(_transport_request())
        client.initialize()
        with self.assertRaises(FrameError):
            client.request(_transport_request())
        self.assertTrue(client.closed)

    def test_client_rejects_duplicate_initialize(self) -> None:
        client = PersistentCppWorkerClient(io.BytesIO(), io.BytesIO())
        client.initialize()
        with self.assertRaises(FrameError):
            client.initialize()

    def test_transport_response_requires_terminated_utf8_identity(self) -> None:
        run = b"r" * 64
        case = b"c\0" + b"\0" * 62
        endpoint = b"e\0" + b"\0" * 31
        raw = RESPONSE.pack(
            1, 1, 1, 560, 1, 2_208_750_000, 2.20875, 1, 0,
            b"\0" * 32, 2, 1, 1, run, case, endpoint, endpoint,
        ) + b"\0" * 24
        with self.assertRaises(FrameError):
            decode_response(HEADER.pack(b"CFDANCF1", len(raw), 2) + raw)

    def test_model_rejects_duplicate_explicit_slice_positions(self) -> None:
        model = KernelModel(elements=2, slices=3, slice_positions_m=(0.0, 5.0, 5.0))
        with self.assertRaises(FrameError):
            model.validate(0.00125)

    def test_wire_integer_overflow_is_a_frame_error(self) -> None:
        value = _transport_request()
        with self.assertRaises(FrameError):
            replace(value, global_step=0x80000000).payload()
        with self.assertRaises(FrameError):
            _kernel_request(0x1_0000_0000, 560, 1, 2.20875, 2_208_750_000).payload()

    def test_checkpoint_rejects_other_case_and_stale_schema(self) -> None:
        adapter = self._adapter()
        path = ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "test_checkpoint_audit.json"
        try:
            adapter.save_checkpoint(path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["case_id"] = "other_case"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CppAdapterError):
                adapter.load_checkpoint(path)
            raw["case_id"] = adapter.case_id
            raw["schema_version"] = "legacy"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CppAdapterError):
                adapter.load_checkpoint(path)
        finally:
            path.unlink(missing_ok=True)

    def test_checkpoint_rejects_staged_state(self) -> None:
        adapter = self._adapter()
        adapter.start()
        try:
            adapter.predict(560, 2.20875, ((0.0, 0.0, 0.0),) * 3)
            path = ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "staged_checkpoint.json"
            try:
                with self.assertRaises(CppAdapterError):
                    adapter.save_checkpoint(path)
            finally:
                path.unlink(missing_ok=True)
        finally:
            adapter.shutdown()

    def test_checkpoint_rejects_non_numeric_identity_without_leaking_value_error(self) -> None:
        adapter = self._adapter()
        path = ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "malformed_checkpoint.json"
        try:
            adapter.save_checkpoint(path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["committed_global_step"] = "560"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CppAdapterError):
                adapter.load_checkpoint(path)
            raw["committed_global_step"] = 560
            raw["committed_time_s"] = "not-a-number"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CppAdapterError):
                adapter.load_checkpoint(path)
        finally:
            path.unlink(missing_ok=True)

    @unittest.skipUnless(WORKER.is_file(), "Stage-local C++ worker has not been built")
    def test_kernel_worker_accepts_predictor_corrector_pair_then_next_step(self) -> None:
        process = subprocess.Popen(
            [str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0,
        )
        assert process.stdin is not None and process.stdout is not None
        try:
            requests = (
                _kernel_request(1, 560, 1, 2.20875, 2_208_750_000),
                _kernel_request(2, 560, 1, 2.20875, 2_208_750_000),
                _kernel_request(3, 561, 2, 2.21000, 2_210_000_000),
            )
            for request in requests:
                process.stdin.write(encode_kernel_request(request))
                process.stdin.flush()
                header = process.stdout.read(KERNEL_HEADER.size)
                self.assertEqual(len(header), KERNEL_HEADER.size)
                length = KERNEL_HEADER.unpack(header)[1]
                body = process.stdout.read(length)
                response = decode_kernel_response(header + body)
                validate_kernel_response(request, response)
            process.stdin.write(KERNEL_HEADER.pack(b"CFDANCF1", 0, 3))
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=10)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            if process.stdout is not None and not process.stdout.closed:
                process.stdout.close()
            if process.stderr is not None and not process.stderr.closed:
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
