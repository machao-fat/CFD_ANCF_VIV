import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_dynamic_startup_v2.campaign import (
    HOT_START_S, PHYSICS, REQUIRED_DYNAMIC_TIME_FILES, _case_metadata, dynamic_state_audit,
)
from src.coupling.stage4f_three_slice_preflight.campaign import _load_identity
from src.coupling.multi_slice_driver.contract import RuntimeConfig


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "results" / "11_stage4f_lowre_benchmark_design_v2_1" / "three_slice_protocol_0_2_1.json"


class TestDynamicStartupV2(unittest.TestCase):
    def setUp(self):
        self.manifest, _ = _load_identity(PROTOCOL)
        self.config = RuntimeConfig(schema_version="0.2.1", case_id=self.manifest.case_id, dt_s=0.0025, timeout_s=60,
            start_time_s=HOT_START_S, coupling_iteration=0, coupling_scheme="explicit_weak", slice_manifest_sha256=self.manifest.slice_manifest_sha256)

    def test_hot_start_is_explicit_new_runtime_identity(self):
        self.assertEqual(self.config.start_time_s, 0.05)
        self.assertNotEqual(self.config.config_sha256, json.loads(PROTOCOL.read_text(encoding="utf-8"))["runtime_config"]["config_sha256"])

    def test_corrected_metadata_has_no_legacy_structure_values(self):
        value = _case_metadata(manifest=self.manifest, config=self.config, spec=self.manifest.slices[0], source=None, role="test")
        self.assertEqual(value["physics"]["L_m"], 50.0)
        self.assertEqual(value["physics"]["nElem"], 16)
        self.assertNotEqual(value["physics"]["top_tension_N"], 1.0e7)
        self.assertNotEqual(value["physics"]["E_Pa"], 2.07e11)

    def test_dynamic_state_requires_every_protocol_file(self):
        with tempfile.TemporaryDirectory() as raw:
            case = Path(raw); (case / "0.05" / "polyMesh").mkdir(parents=True); (case / "0.05" / "uniform").mkdir(); (case / "0").mkdir()
            for relative in REQUIRED_DYNAMIC_TIME_FILES:
                target = case / "0.05" / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(relative, encoding="utf-8")
            (case / "0" / "motionScale").write_text("scale", encoding="utf-8")
            audit = dynamic_state_audit(case)
            self.assertEqual(len(audit["dynamic_time_files"]), 7)
            (case / "0.05" / "Uf").unlink()
            with self.assertRaises(FileNotFoundError): dynamic_state_audit(case)

    def test_parent_manifest_is_unchanged_three_slice_identity(self):
        self.assertEqual(len(self.manifest.slices), 3)
        self.assertEqual([x.slice_length_m for x in self.manifest.slices], [50.0 / 3.0] * 3)

