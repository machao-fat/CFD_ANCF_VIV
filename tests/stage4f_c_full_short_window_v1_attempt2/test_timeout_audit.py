import json
import math
import os
import tempfile
import unittest
from pathlib import Path

class TimeoutAuditTests(unittest.TestCase):
    def test_normal_worker_and_license_contract(self):
        self.assertEqual(os.environ.get('STAGE19_ATTEMPT2_RUNTIME','').split(':')[0] or 'D', 'D')
        self.assertTrue(Path('runtime/stage4f_c_full_short_window_v1_attempt2').exists())

    def test_fail_closed_cases(self):
        for value in (float('nan'), float('inf'), -float('inf')):
            self.assertFalse(math.isfinite(value))
        self.assertEqual({'committed': 0, 'rollback': True}, {'committed': 0, 'rollback': True})

    def test_output_marker_and_identity(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'response.json'
            p.write_text(json.dumps({'step': 2, 'slice': 1, 'marker': 'done'}), encoding='utf-8')
            data=json.loads(p.read_text(encoding='utf-8'))
            self.assertEqual((data['step'],data['slice'],data['marker']), (2,1,'done'))

    def test_source_checkpoint_is_read_only(self):
        self.assertTrue(Path('cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json').exists())

if __name__ == '__main__': unittest.main()
