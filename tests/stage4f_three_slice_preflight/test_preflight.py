import json
import unittest
from pathlib import Path

from src.coupling.stage4f_three_slice_preflight.campaign import _load_identity, _physics

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / 'results' / '11_stage4f_lowre_benchmark_design_v2_1' / 'three_slice_protocol_0_2_1.json'

class TestStage4FPreflight(unittest.TestCase):
    def test_identity(self):
        manifest, config = _load_identity(PROTOCOL)
        self.assertEqual(len(manifest.slices), 3); self.assertEqual(manifest.reference_length_m, 50.0)
        self.assertEqual(config.dt_s, 0.0025)
    def test_physics(self):
        manifest, config = _load_identity(PROTOCOL); value = _physics(manifest, config)
        self.assertEqual(value['Re'], 100.0); self.assertEqual(value['nElem'], 16)
        self.assertEqual(len(value['physics_sha256']), 64)
    def test_protocol_json_is_finite(self):
        value=json.loads(PROTOCOL.read_text(encoding='utf-8'))
        self.assertEqual(value['manifest']['case_id'], 'stage4f_lowre_v2_1_uniform_3slice')

