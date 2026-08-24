from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from coupling.cpp_worker_confirm_v1.contracts import CppConfirmContract, REAL_AUTHORIZATION_TOKEN
from coupling.cpp_worker_confirm_v1.production_factory import (
    ProductionFactoryError, build_existing_openfoam_backend_factory,
    build_persistent_slice_factory,
)
from coupling.multi_slice_driver.contract import SliceExchangePaths, SliceSpec, build_slice_manifest, build_config
from coupling.multi_slice_mapping.mapping import RuntimeConfig, SliceManifest


class ProductionFactoryTests(unittest.TestCase):
    def _contract(self, root: Path) -> CppConfirmContract:
        source = root / "source.json"
        source.write_text('{"status":"committed"}\n', encoding="utf-8")
        return CppConfirmContract(
            stage_id="stage4f_d_cpp_worker_confirm_v1_real_002", run_id="run_real_002",
            case_id="case_real_002", runtime=root / "runtime", results=root / "results",
            source_checkpoint=source, source_checkpoint_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            allow_real_external_processes=True, authorization=REAL_AUTHORIZATION_TOKEN)

    def test_factory_is_lazy_and_constructs_only_requested_slice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); contract = self._contract(root)
            specs = [SliceSpec(i, 1.0 + i, 1.0) for i in range(3)]
            manifest = SliceManifest.from_mapping(build_slice_manifest(contract.case_id, specs))
            config = RuntimeConfig.from_mapping(build_config(case_id=contract.case_id, dt_s=.00125,
                timeout_s=1.0, specs=specs, start_time_s=2.2075))
            made = []
            def backend_factory(sid, path):
                made.append((sid, path))
                return object()
            factory = build_persistent_slice_factory(
                contract=contract, authorization=REAL_AUTHORIZATION_TOKEN,
                manifest=manifest, runtime_config=config,
                paths_factory=lambda sid, path: SliceExchangePaths(path / "exchange", manifest.slices[sid]),
                seed_factory=lambda sid: {"slice_id": sid, "step": 559, "time_s": 2.2075},
                backend_factory=backend_factory)
            self.assertEqual(made, [])
            adapter = factory(1, contract.runtime / "slice_1")
            self.assertEqual(made[0][0], 1)
            self.assertEqual(adapter.slice_id, 1)

    def test_factory_rejects_disabled_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); contract = self._contract(root)
            disabled = CppConfirmContract(**{**contract.__dict__, "allow_real_external_processes": False,
                                             "authorization": None})
            specs = [SliceSpec(i, 1.0 + i, 1.0) for i in range(3)]
            manifest = SliceManifest.from_mapping(build_slice_manifest(contract.case_id, specs))
            config = RuntimeConfig.from_mapping(build_config(case_id=contract.case_id, dt_s=.00125,
                timeout_s=1.0, specs=specs, start_time_s=2.2075))
            with self.assertRaises(Exception):
                build_persistent_slice_factory(contract=disabled, authorization=REAL_AUTHORIZATION_TOKEN,
                    manifest=manifest, runtime_config=config, paths_factory=lambda sid, path: None,
                    seed_factory=lambda sid: None, backend_factory=lambda sid, path: None)

    def test_existing_openfoam_backend_is_constructed_lazily(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); contract = self._contract(root)
            specs = [SliceSpec(i, 1.0 + i, 1.0) for i in range(3)]
            manifest = SliceManifest.from_mapping(build_slice_manifest(contract.case_id, specs))
            config = RuntimeConfig.from_mapping(build_config(case_id=contract.case_id, dt_s=.00125,
                timeout_s=1.0, specs=specs, start_time_s=2.2075))
            cases = {i: root / f"case_{i}" for i in range(3)}
            for case in cases.values(): case.mkdir()
            library = root / "libancfFileMotion.so"; library.write_bytes(b"offline-placeholder")
            backend_factory = build_existing_openfoam_backend_factory(
                contract=contract, manifest=manifest, runtime_config=config,
                case_by_slice=cases, exchange_root=root / "exchange", library=library,
                run_id=contract.run_id)
            backend = backend_factory(0, contract.runtime / "slice_0")
            self.assertEqual(backend.slice_id, 0)
            self.assertFalse(getattr(backend, "_persistent_started", False))


if __name__ == "__main__":
    unittest.main()
