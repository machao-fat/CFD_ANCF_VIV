from __future__ import annotations

import json
import sys
import io
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_confirm_v1.cpp_adapter import CppAdapterError, CppKernelCampaignAdapter, _model_contract_sha256
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    FrameError, KernelModel, KernelStepRequest, RESPONSE_FIELD_SEMANTICS,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import FrameError as TransportFrameError, StepRequest
from coupling.cpp_worker_persistent_ipc_v1.mapping_contract import SourceMapping
from coupling.cpp_worker_persistent_ipc_v1.worker_client import PersistentCppWorkerClient


class ContractRepairTests(unittest.TestCase):
    def _transport_request(self) -> StepRequest:
        return StepRequest(
            sequence=1, global_step=1, case_local_bridge_step=1,
            integer_tick=1_250_000, time_s=0.00125, dt_s=0.00125,
            request_id=1, transaction_id=2, run_id="run", case_id="case",
            q=(0.0,), qdot=(0.0,), force=(0.0,),
        )

    def test_low_level_client_times_out_and_becomes_terminal(self):
        class BlockingReader:
            def read(self, _size: int) -> bytes:
                time.sleep(0.2)
                return b""

        client = PersistentCppWorkerClient(BlockingReader(), io.BytesIO(), timeout_s=0.01)
        client.initialized = True
        with self.assertRaises(TransportFrameError):
            client.request(self._transport_request())
        self.assertTrue(client.closed)

    def test_low_level_client_rejects_response_magic_before_decode(self):
        value = self._transport_request()
        bad = b"BADMAGIC" + (0).to_bytes(4, "little") + (2).to_bytes(4, "little")
        client = PersistentCppWorkerClient(io.BytesIO(bad), io.BytesIO(), timeout_s=0.2)
        client.initialized = True
        with self.assertRaises(TransportFrameError):
            client.request(value)
        self.assertTrue(client.closed)

    def test_low_level_client_rejects_step_lineage_gap_before_write(self):
        client = PersistentCppWorkerClient(io.BytesIO(), io.BytesIO(), timeout_s=0.2)
        client.initialized = True
        # Supply a valid response frame only for the first request is not
        # needed here; the first call must fail at the transport EOF and poison
        # the client, so use the state fields directly to exercise the guard.
        client.last_sequence = 1
        client.last_global_step = 1
        client.last_bridge_step = 1
        client.last_tick = 1_250_000
        client.last_time_s = 0.00125
        client.last_dt_s = 0.00125
        with self.assertRaises(TransportFrameError):
            client.request(StepRequest(
                sequence=2, global_step=3, case_local_bridge_step=3,
                integer_tick=3_750_000, time_s=0.00375, dt_s=0.00125,
                request_id=3, transaction_id=4, run_id="run", case_id="case",
                q=(0.0,), qdot=(0.0,), force=(0.0,),
            ))
        self.assertTrue(client.closed)

    def test_mapping_rejects_subnanosecond_step_ambiguity(self):
        with self.assertRaises(TransportFrameError):
            SourceMapping(0, 0.0, 0, 1.0000000005e-9)

    def test_canonical_boundary_identity_is_bound_to_values(self):
        model = KernelModel(elements=1, slices=1, fixed_dof=(0, 1, 2, 6, 7),
                            prescribed_values=(0.0, 0.0, 0.0, 0.0, 1.0))
        with self.assertRaises(FrameError):
            model.validate(0.00125)

    def test_strict_adapter_requires_mass_and_external_contract_hash(self):
        class Worker:
            def start(self) -> None: pass
            def stop(self) -> None: pass
        model = KernelModel(elements=1, slices=1)
        n = model.ndof
        kwargs = dict(worker=Worker(), model=model, request_factory=lambda **value: SimpleNamespace(**value),
                      run_id="strict_run", case_id="strict_case", source_global_step=559,
                      source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
                      q=(0.0,) * n, qdot=(0.0,) * n, qddot=(0.0,) * n,
                      base_load=(0.0,) * n, slice_count=3,
                      strict_numerical_contract=True)
        with self.assertRaises(CppAdapterError):
            CppKernelCampaignAdapter(**kwargs)
        mass = tuple(1.0 if row == col else 0.0 for row in range(n) for col in range(n))
        expected = _model_contract_sha256(model, mass)
        self.assertIsNotNone(expected)
        with self.assertRaises(CppAdapterError):
            CppKernelCampaignAdapter(**kwargs, mass_matrix=mass, expected_model_contract_sha256="0" * 64)
        adapter = CppKernelCampaignAdapter(**kwargs, mass_matrix=mass,
                                           expected_model_contract_sha256=expected)
        self.assertTrue(adapter.strict_numerical_contract)

    def test_v1_response_force_field_semantics_are_explicit(self) -> None:
        self.assertEqual(RESPONSE_FIELD_SEMANTICS["external_force"], "total_Qext")
        self.assertEqual(RESPONSE_FIELD_SEMANTICS["generalized_force"], "total_Qext_alias")
        self.assertNotEqual(RESPONSE_FIELD_SEMANTICS["external_force"], "cfd_only_force")

    def test_kernel_model_rejects_nan_top_tension_and_boolean_numbers(self) -> None:
        model = KernelModel(top_tension_N=float("nan"))
        with self.assertRaises(FrameError):
            model.validate(0.00125)
        model = KernelModel(elements=True)
        with self.assertRaises(FrameError):
            model.validate(0.00125)

    def test_kernel_payload_rejects_non_numeric_mass_matrix(self) -> None:
        model = KernelModel(elements=1, slices=1, slice_positions_m=(0.0,))
        n = model.ndof
        request = KernelStepRequest(
            sequence=1, global_step=1, case_local_bridge_step=1,
            integer_tick=1_250_000, time_s=0.00125, dt_s=0.00125,
            request_id=1, transaction_id=2, run_id="r", case_id="c", model=model,
            q=(0.0,) * n, qdot=(0.0,) * n, qddot=(0.0,) * n,
            base_load=(0.0,) * n, slice_force=(0.0,) * 3,
            mass_matrix=("bad",),
        )
        with self.assertRaises(FrameError):
            request.payload()

    def test_transport_payload_rejects_non_numeric_state(self) -> None:
        request = StepRequest(
            1, 1, 1, 1_250_000, 0.00125, 0.00125, 1, 2,
            "run", "case", ("bad",), (0.0,), (0.0,),
        )
        with self.assertRaises(TransportFrameError):
            request.payload()

    def _adapter(self) -> CppKernelCampaignAdapter:
        class Worker:
            def start(self) -> None:
                return None
            def stop(self) -> None:
                return None
        return CppKernelCampaignAdapter(
            worker=Worker(), model=object(), request_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            run_id="repair_run", case_id="repair_case", source_global_step=559,
            source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
            q=(0.0, 0.0, 0.0), qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0),
            base_load=(0.0, 0.0, 0.0), slice_count=3,
        )

    def test_failed_checkpoint_load_does_not_mutate_state(self) -> None:
        adapter = self._adapter()
        path = ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v2" / "checkpoint.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            adapter.save_checkpoint(path)
            original = adapter.state_view()
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["state_view"]["q"] = [1.0]
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CppAdapterError):
                adapter.load_checkpoint(path)
            self.assertEqual(adapter.state_view(), original)
        finally:
            path.unlink(missing_ok=True)

    def test_invalid_adapter_identity_is_rejected(self) -> None:
        with self.assertRaises(CppAdapterError):
            self._adapter_with(run_id=None)
        with self.assertRaises(CppAdapterError):
            self._adapter_with(source_tick=2_207_500_001)

    def test_adapter_rejects_source_dimension_mismatch(self) -> None:
        class Worker:
            def start(self) -> None: return None
            def stop(self) -> None: return None
        with self.assertRaises(CppAdapterError):
            CppKernelCampaignAdapter(
                worker=Worker(), model=SimpleNamespace(ndof=3),
                request_factory=lambda **kwargs: SimpleNamespace(**kwargs),
                run_id="repair_run", case_id="repair_case", source_global_step=559,
                source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125,
                q=(0.0, 0.0), qdot=(0.0, 0.0), qddot=(0.0, 0.0),
                base_load=(0.0, 0.0), slice_count=3,
            )

    def _adapter_with(self, **changes: object) -> CppKernelCampaignAdapter:
        values = dict(run_id="repair_run", case_id="repair_case", source_global_step=559,
                      source_time_s=2.2075, source_tick=2_207_500_000, dt_s=0.00125)
        values.update(changes)
        class Worker:
            def start(self) -> None: return None
            def stop(self) -> None: return None
        return CppKernelCampaignAdapter(
            worker=Worker(), model=object(), request_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            **values, q=(0.0, 0.0, 0.0), qdot=(0.0, 0.0, 0.0), qddot=(0.0, 0.0, 0.0),
            base_load=(0.0, 0.0, 0.0), slice_count=3,
        )


if __name__ == "__main__":
    unittest.main()
