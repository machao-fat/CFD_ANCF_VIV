from __future__ import annotations
import json,subprocess
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; BASE=ROOT/'tools/three_slice_force_contract_smoke_v2/three_slice_force_contract_smoke_v2_run_001.json'; OUT=Path(__file__).with_name('moving_mesh_patch_consistency_fix_and_1s_retry_v1_contract.json')
def main():
 if OUT.exists():raise RuntimeError('refusing to overwrite contract')
 x=json.loads(BASE.read_text()); x.update({'schema_version':'moving-mesh-patch-consistency-fix-and-1s-retry-v1','run_id':'moving_mesh_patch_consistency_1s_retry_v1_run_001','case_id':'moving_mesh_patch_consistency_1s_retry_v1_case_001','git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'timestamp_utc':datetime.now(timezone.utc).isoformat(),'moving_mesh_patch_contract':{'required_fields_from_dynamic_mesh_and_adapter':['pointDisplacement','cellDisplacement'],'symmetry_plane_rule':'a symmetryPlane mesh patch requires a symmetryPlane field patch','preflight_required':True,'mesh_tracking_tolerance_m':1e-8,'snapshot_interval_s':0.1}}); OUT.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');print(OUT)
if __name__=='__main__':main()
