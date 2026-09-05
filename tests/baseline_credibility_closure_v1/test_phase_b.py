from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "src"))
from coupling.moment_mapping_audit_v1.audit import audit

RESULT = ROOT / "results" / "moment_mapping_audit_v1" / "moment_mapping_audit_v1_2.json"
POSITIONS = (8.333333333333334, 25.0, 41.666666666666664)


def q_curve() -> list[float]:
    q: list[float] = []
    for node in range(17):
        s = 50.0 * node / 16.0
        q.extend((s, 0.25*s*s/50.0, s, 1.0, 0.5*s/25.0, 1.0))
    return q


def run(forces, origin=(0.0, 0.0, 0.0)):
    return audit(q_curve(), forces, positions_m=POSITIONS, origin=origin, delta_q=[((i % 11)-5)*0.013 for i in range(102)])


class PhaseBAnalyticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(RESULT.read_text(encoding="utf-8"))

    def assert_analytic(self, data) -> None:
        self.assertLess(data["force_error_normalized"], 1.0e-10)
        self.assertLess(data["moment_error_normalized_v2"], 1.0e-10)
        self.assertLess(data["virtual_work"]["normalized_error"], 1.0e-10)

    def test_single_point_force_analytic_moment(self): self.assert_analytic(run(((3.,-2.,1.),(0.,0.,0.),(0.,0.,0.))))
    def test_off_axis_point_force(self): self.assert_analytic(run(((0.,0.,0.),(4.,-1.,2.),(0.,0.,0.))))
    def test_pure_couple_zero_resultant(self):
        data=run(((2.,3.,0.),(-2.,-3.,0.),(0.,0.,0.))); self.assert_analytic(data); self.assertLess(sum(x*x for x in data['fluid_resultant_N']),1e-24)
    def test_non_symmetric_three_slice(self): self.assert_analytic(run(((4.,-1.,2.),(-3.,2.,-1.),(1.,5.,3.))))
    def test_translated_origin_identity(self):
        forces=((4.,-1.,2.),(-3.,2.,-1.),(1.,5.,3.)); first=run(forces); origin=(1.3,-2.1,.7); second=run(forces,origin); expected=tuple(first['fluid_moment_Nm'][i]-((origin[1]*first['fluid_resultant_N'][2]-origin[2]*first['fluid_resultant_N'][1]),(origin[2]*first['fluid_resultant_N'][0]-origin[0]*first['fluid_resultant_N'][2]),(origin[0]*first['fluid_resultant_N'][1]-origin[1]*first['fluid_resultant_N'][0]))[i] for i in range(3)); self.assertLess(max(abs(a-b) for a,b in zip(expected,second['fluid_moment_Nm'])),1e-12); self.assert_analytic(second)
    def test_near_zero_moment_uses_conditioned_metric(self): self.assert_analytic(run(((1e9,2e9,0.),(-1e9,-2e9,0.),(1e-6,-1e-6,0.))))
    def test_large_magnitude_cancellation(self): self.assert_analytic(run(((1e12,-3e12,0.),(-1e12,3e12+1e-3,0.),(0.,-1e-3,0.))))
    def test_compensated_sum_comparison_is_recorded(self): self.assertGreaterEqual(self.evidence['analytic_cases'][-1]['compensated_comparison']['moment_absolute_difference_Nm'],0.0)
    def test_h_transpose_virtual_work_regression(self): self.assert_analytic(run(((4.,-1.,2.),(-3.,2.,-1.),(1.,5.,3.))))
    def test_historical_stage385_is_unchanged(self):
        v3=json.loads((ROOT/'results/solver_validation_v3/three_slice_statistical_contract_v3.json').read_text(encoding='utf-8'))
        entry=v3['source_segments'][1]; path=Path(entry['mapping_path']); self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),entry['mapping_sha256']); self.assertEqual(v3['mapping_integrity']['status'],'fail')


if __name__ == '__main__': unittest.main()
