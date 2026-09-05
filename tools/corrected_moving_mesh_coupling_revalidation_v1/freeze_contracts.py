"""Freeze fresh corrected 1 s and conditional 20 s contracts before CFD."""
from __future__ import annotations
import hashlib, json, subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'tools/three_slice_force_contract_smoke_v2/three_slice_force_contract_smoke_v2_run_001.json'
QUALITY=ROOT/'tools/numerical_quality_evidence_closure_v1/openfoam_numerical_quality_contract_v2.json'
OUT=Path(__file__).parent
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    base=json.loads(BASE.read_text(encoding='utf-8')); commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    for duration, label in ((1.0,'1s'),(20.0,'20s')):
        out=OUT/f'corrected_moving_mesh_coupling_revalidation_v1_{label}_contract.json'
        if out.exists(): raise RuntimeError(f'refusing to overwrite {out.name}')
        value=dict(base); value.update({'schema_version':'corrected-moving-mesh-coupling-revalidation-v1','run_id':f'corrected_moving_mesh_{label}_run_001','case_id':f'corrected_moving_mesh_{label}_case_001','git_commit':commit,'timestamp_utc':datetime.now(timezone.utc).isoformat(),'duration_s':duration,'number_of_steps':round(duration/0.005),'quality_contract_v2':{'source':str(QUALITY.relative_to(ROOT)).replace('\\','/'),'sha256':digest(QUALITY),'frozen_before_run':True},'moving_mesh_contract':{'reference_cylinder_centroid_xyz_m':[0.0,0.0,0.5],'snapshot_interval_s':0.1,'required_snapshot_times_s':([0.0,0.1,0.5,1.0] if duration==1 else [0.0,1.0,5.0,10.0,15.0,20.0]),'mesh_motion_error_tolerance_m':1e-8,'point_displacement_error_tolerance_m':1e-8,'distinct_motion_threshold_m':1e-8,'distinct_geometry_threshold_m':1e-9,'field_comparison_times_s':([0.1,0.5,1.0] if duration==1 else [1.0,5.0,10.0,15.0,20.0]),'full_mesh_snapshots':'time/polyMesh/points at every 0.1 s output'}})
        out.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(out)
if __name__=='__main__': main()
