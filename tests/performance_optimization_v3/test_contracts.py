from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coupling.performance_optimization_v3.contracts import make_contract, validate_v3_contract
from coupling.performance_optimization_v2.openfoam_persistent import PersistentOpenFOAMSliceProcess
from coupling.multi_slice_real_campaign.campaign import _wsl_path


class V3ContractTests(unittest.TestCase):
    def test_contract_is_bounded_and_in_memory_explicit(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            runtime = Path(temp) / "performance_optimization_v3"
            source = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_case/checkpoints/checkpoint_step00000560_8d8b936ea093.json")
            value = make_contract(project_root=Path("D:/研二文件/开题准备/CFD_ANCF_VIV"), runtime=runtime,
                                  source_checkpoint=source, run_id="v3_run", case_id="v3_case",
                                  matlab_executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
            validate_v3_contract(value, Path("D:/研二文件/开题准备/CFD_ANCF_VIV"))
            self.assertTrue(value["matlab_in_memory_state"])
            self.assertFalse(value["persistent_ipc"])
            self.assertTrue(value["wsl_native_case_staging"])
            self.assertEqual(value["steps"], 40)

    def test_ipc_cannot_be_relabelled(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path("D:/研二文件/开题准备/CFD_ANCF_VIV")
            source = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_case/checkpoints/checkpoint_step00000560_8d8b936ea093.json")
            value = make_contract(project_root=root, runtime=Path(temp) / "r", source_checkpoint=source,
                                  run_id="v3_run2", case_id="v3_case2", matlab_executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
            value["persistent_ipc"] = True
            with self.assertRaises(ValueError): validate_v3_contract(value, root)

    def test_gamg_cache_accepts_single_explicit_entry(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            case = Path(temp)
            system = case / "system"
            system.mkdir()
            fv_solution = system / "fvSolution"
            fv_solution.write_text(
                "solvers { p { solver GAMG; cacheAgglomeration no; tolerance 1e-8; } "
                "pcorr { solver GAMG; tolerance 1e-2; } }\n",
                encoding="utf-8",
            )
            process = PersistentOpenFOAMSliceProcess.__new__(PersistentOpenFOAMSliceProcess)
            process.case = case
            process.slice_id = 0
            process._enable_gamg_agglomeration_cache()
            self.assertEqual(fv_solution.read_text(encoding="utf-8").count("cacheAgglomeration yes;"), 1)

    def test_native_wsl_staging_path_and_unc_round_trip(self):
        process = PersistentOpenFOAMSliceProcess.__new__(PersistentOpenFOAMSliceProcess)
        process.run_id = "stage96/v3 unsafe value"
        process.slice_id = 2
        path = process._native_stage_path()
        self.assertEqual(path, "/tmp/cfd_ancf_viv_stage96/stage96_v3_unsafe_value/slice_0002")
        unc = process._unc_from_wsl(path)
        self.assertEqual(_wsl_path(unc), path)

    def test_native_checkpoint_direct_is_explicit_and_bounded(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path("D:/研二文件/开题准备/CFD_ANCF_VIV")
            source = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_case/checkpoints/checkpoint_step00000560_8d8b936ea093.json")
            value = make_contract(project_root=root, runtime=Path(temp) / "direct", source_checkpoint=source,
                                  run_id="v3_direct", case_id="v3_direct_case", matlab_executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
            validate_v3_contract(value, root)
            self.assertTrue(value["native_checkpoint_direct"])

    def test_native_checkpoint_direct_rejects_missing_flag(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path("D:/研二文件/开题准备/CFD_ANCF_VIV")
            source = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_case/checkpoints/checkpoint_step00000560_8d8b936ea093.json")
            value = make_contract(project_root=root, runtime=Path(temp) / "direct_missing", source_checkpoint=source,
                                  run_id="v3_direct_missing", case_id="v3_direct_missing_case", matlab_executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
            value["native_checkpoint_direct"] = False
            with self.assertRaises(ValueError):
                validate_v3_contract(value, root)

    def test_checkpoint_hash_cache_without_native_staging_is_explicit(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path("D:/研二文件/开题准备/CFD_ANCF_VIV")
            source = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_case/checkpoints/checkpoint_step00000560_8d8b936ea093.json")
            value = make_contract(
                project_root=root, runtime=Path(temp) / "cache", source_checkpoint=source,
                run_id="v3_cache", case_id="v3_cache_case",
                matlab_executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe",
                wsl_native_case_staging=False, native_checkpoint_direct=False,
                checkpoint_hash_cache=True, disable_force_coeffs_output=True,
            )
            validate_v3_contract(value, root)
            self.assertFalse(value["wsl_native_case_staging"])
            self.assertFalse(value["native_checkpoint_direct"])
            self.assertTrue(value["checkpoint_hash_cache"])
            self.assertEqual(value["protocol_poll_interval_s"], 0.001)

    def test_binary_field_write_format_is_explicit(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path("D:/研二文件/开题准备/CFD_ANCF_VIV")
            source = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_case/checkpoints/checkpoint_step00000560_8d8b936ea093.json")
            value = make_contract(project_root=root, runtime=Path(temp) / "binary", source_checkpoint=source,
                                  run_id="v3_binary", case_id="v3_binary_case",
                                  matlab_executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe",
                                  wsl_native_case_staging=False, native_checkpoint_direct=False,
                                  field_write_format="binary")
            validate_v3_contract(value, root)
            self.assertEqual(value["field_write_format"], "binary")

    def test_direct_wsl_exec_is_explicit(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path("D:/研二文件/开题准备/CFD_ANCF_VIV")
            source = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_case/checkpoints/checkpoint_step00000560_8d8b936ea093.json")
            value = make_contract(project_root=root, runtime=Path(temp) / "direct_wsl", source_checkpoint=source,
                                  run_id="v3_direct_wsl", case_id="v3_direct_wsl_case",
                                  matlab_executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe",
                                  wsl_native_case_staging=False, native_checkpoint_direct=False,
                                  direct_wsl_exec=True)
            validate_v3_contract(value, root)
            self.assertTrue(value["direct_wsl_exec"])

    def test_incremental_io_controls_are_explicit_and_bounded(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path("D:/研二文件/开题准备/CFD_ANCF_VIV")
            source = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_case/checkpoints/checkpoint_step00000560_8d8b936ea093.json")
            value = make_contract(
                project_root=root, runtime=Path(temp) / "io", source_checkpoint=source,
                run_id="v3_io", case_id="v3_io_case",
                matlab_executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe",
                wsl_native_case_staging=False, native_checkpoint_direct=False,
                field_write_precision=10, ephemeral_exchange_io=True,
            )
            validate_v3_contract(value, root)
            self.assertEqual(value["field_write_precision"], 10)
            self.assertTrue(value["ephemeral_exchange_io"])
            value["field_write_precision"] = 7
            from coupling.performance_optimization_v2.contracts import contract_hash
            value["contract_sha256"] = contract_hash(value)
            with self.assertRaises(ValueError):
                validate_v3_contract(value, root)

    def test_startup_overlap_controls_are_explicit(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path("D:/研二文件/开题准备/CFD_ANCF_VIV")
            source = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_case/checkpoints/checkpoint_step00000560_8d8b936ea093.json")
            value = make_contract(project_root=root, runtime=Path(temp) / "startup", source_checkpoint=source,
                                  run_id="v3_startup", case_id="v3_startup_case",
                                  matlab_executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe",
                                  wsl_native_case_staging=False, native_checkpoint_direct=False,
                                  prewarm_openfoam_startup=True, reuse_parallel_executor=True)
            validate_v3_contract(value, root)
            self.assertTrue(value["prewarm_openfoam_startup"])
            self.assertTrue(value["reuse_parallel_executor"])
            value["reuse_parallel_executor"] = "yes"
            from coupling.performance_optimization_v2.contracts import contract_hash
            value["contract_sha256"] = contract_hash(value)
            with self.assertRaises(ValueError):
                validate_v3_contract(value, root)

    def test_poll_interval_is_bounded(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path("D:/研二文件/开题准备/CFD_ANCF_VIV")
            source = Path("D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_case/checkpoints/checkpoint_step00000560_8d8b936ea093.json")
            value = make_contract(project_root=root, runtime=Path(temp) / "poll", source_checkpoint=source,
                                  run_id="v3_poll", case_id="v3_poll_case",
                                  matlab_executable=r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe",
                                  wsl_native_case_staging=False, native_checkpoint_direct=False,
                                  openfoam_poll_interval_s=0.001)
            validate_v3_contract(value, root)
            value["openfoam_poll_interval_s"] = 0.0001
            from coupling.performance_optimization_v2.contracts import contract_hash
            value["contract_sha256"] = contract_hash(value)
            with self.assertRaises(ValueError):
                validate_v3_contract(value, root)
