from __future__ import annotations
import importlib.util,shutil,tempfile,unittest
from pathlib import Path
from coupling.moving_mesh_patch_compatibility_v1.audit import audit
from coupling.slice_independence_audit_v1.audit import sensitivity_evidence_status
ROOT=Path(__file__).resolve().parents[2]
class PatchCompatibilityTests(unittest.TestCase):
 def generated(self):
  d=tempfile.TemporaryDirectory(); case=Path(d.name)/'case';(case/'0').mkdir(parents=True);shutil.copytree(ROOT/'cases/openfoam/single_slice_ancf_fsi/constant',case/'constant');(case/'system').mkdir()
  spec=importlib.util.spec_from_file_location('launcher',ROOT/'tools/three_slice_force_contract_smoke_v1/run_smoke.py');m=importlib.util.module_from_spec(spec);assert spec.loader;spec.loader.exec_module(m)
  m.put(case/'0/pointDisplacement',m.POINT);m.put(case/'0/cellDisplacement',m.CELL);m.put(case/'constant/dynamicMeshDict',m.DYNAMIC);m.put(case/'system/preciceDict','namePointDisplacement pointDisplacement; nameCellDisplacement cellDisplacement;');return d,case
 def test_generated_point_and_cell_symmetry_patch_compatibility(self):
  d,c=self.generated();self.addCleanup(d.cleanup);x=audit(c);self.assertEqual(x['MESH_FIELD_PATCH_COMPATIBILITY'],'PASS');self.assertEqual(x['field_patch_types']['pointDisplacement']['lower'],'symmetryPlane');self.assertEqual(x['field_patch_types']['pointDisplacement']['upper'],'symmetryPlane');self.assertEqual(x['field_patch_types']['cellDisplacement']['lower'],'symmetryPlane');self.assertEqual(x['field_patch_types']['cellDisplacement']['upper'],'symmetryPlane')
 def test_synthetic_zero_gradient_on_symmetry_plane_fails(self):
  d,c=self.generated();self.addCleanup(d.cleanup);p=c/'0/cellDisplacement';p.write_text(p.read_text().replace('lower { type symmetryPlane; }','lower { type zeroGradient; }'));self.assertEqual(audit(c)['MESH_FIELD_PATCH_COMPATIBILITY'],'FAIL')
 def test_controlled_sensitivity_regression_gate(self):self.assertEqual(sensitivity_evidence_status(geometry_distinct=True,u_distinct=True,p_distinct=True,fy_difference_N=1.0),'pass')
 def test_failed_runtime_is_read_only_evidence(self):self.assertTrue((ROOT/'runtime/corrected_moving_mesh_1s_run_001/logs/fluid_0000.stderr').is_file())
if __name__=='__main__':unittest.main()
