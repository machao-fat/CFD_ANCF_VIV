import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_001 as launch
from coupling.cpp_worker_confirm_v1.contracts import CppConfirmContract, ContractError, REAL_AUTHORIZATION_TOKEN
from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest
from coupling.cpp_worker_confirm_v1.numerical_contract import normalize_model


class FreshT0LaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.preflight = json.loads(
            (ROOT / "results/239_cpp_worker_fresh_t0_real_preflight_v1/fresh_t0_real_launch_preflight.json")
            .read_text(encoding="utf-8"))

    def test_preflight_passes_without_launch(self):
        self.assertTrue(all(self.preflight["checks"].values()))
        self.assertFalse(self.preflight["launch_performed"])
        self.assertEqual(self.preflight["real_process_starts"],
                         {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})

    def test_fresh_contract_is_exactly_bounded(self):
        contract = CppConfirmContract(
            stage_id=launch.STAGE_ID, run_id=launch.RUN_ID, case_id=launch.CASE_ID,
            runtime=launch.RUNTIME, results=launch.RESULTS,
            source_checkpoint=launch.SOURCE, source_checkpoint_sha256=launch.SOURCE_SHA256,
            source_global_step=0, source_time_s=0.0, source_tick=0, steps=40,
            segment_duration_s=0.05, global_dt_s=0.00125, slice_count=3,
            allow_real_external_processes=True, authorization=REAL_AUTHORIZATION_TOKEN)
        contract.validate(ROOT)
        with self.assertRaises(ContractError):
            CppConfirmContract(
                stage_id=launch.STAGE_ID, run_id=launch.RUN_ID + "_bad", case_id=launch.CASE_ID,
                runtime=launch.RUNTIME, results=launch.RESULTS,
                source_checkpoint=launch.SOURCE, source_checkpoint_sha256=launch.SOURCE_SHA256,
                source_global_step=0, source_time_s=0.0, source_tick=0, steps=41,
                segment_duration_s=0.05125, global_dt_s=0.00125, slice_count=3,
                allow_real_external_processes=True, authorization=REAL_AUTHORIZATION_TOKEN).validate(ROOT)

    def test_adapter_accepts_audited_static_state_without_starting(self):
        model, *_ = launch._fresh_fixture()
        model = normalize_model(model)
        worker = KernelWorker(launch.WORKER_EXE, launch.RUNTIME / "offline_test_process",
                              launch.RUN_ID + "_test", launch.CASE_ID + "_test",
                              expected_model_contract_sha256=launch.EXPECTED_MODEL_CONTRACT_SHA256)
        adapter = CppKernelCampaignAdapter.from_checkpoint(
            worker=worker, model=model, request_factory=KernelStepRequest,
            checkpoint=launch.SOURCE, expected_sha256=launch.SOURCE_SHA256,
            run_id=launch.RUN_ID + "_test", case_id=launch.CASE_ID + "_test",
            dt_s=0.00125, base_load=launch._fresh_fixture()[-1], slice_count=3,
            mass_matrix=launch._source_mass_matrix(),
            expected_model_contract_sha256=launch.EXPECTED_MODEL_CONTRACT_SHA256)
        self.assertEqual((adapter.source_global_step, adapter.source_time_s, adapter.source_tick), (0, 0.0, 0))
        self.assertEqual(adapter.start_count, 0)

    def test_no_real_processes_are_started_by_import_or_preflight(self):
        self.assertEqual(self.preflight["owned_residual"], 0)
        self.assertFalse(self.preflight["launch_performed"])
        self.assertFalse(self.preflight["old_runtime_reused"])

    def test_launcher_requires_explicit_authorization_flag(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/cpp_worker_fresh_t0_v1/run_authorized_fresh_t0_001.py")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--authorize-real", result.stderr)


if __name__ == "__main__":
    unittest.main()
