"""Read-only completion of the already-run dt-half zero-motion preflight."""
from __future__ import annotations
import hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).parent; sys.path.insert(0,str(ROOT/'src'))
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log
from coupling.slice_independence_audit_v1.audit import parse_forces
from quality_v4 import evaluate_quality_v4
RUN='parallel_explicit_fsi_timestep_stability_preflight_v1_run_001'; RUNTIME=ROOT/'runtime'/RUN; RESULTS=ROOT/'results'/RUN; PRE=ROOT/'results/fixed_cylinder_precursor_initialization_contract_v1_run_002/PRECURSOR_STATE_V1'; V4=HERE/'openfoam_quality_contract_v4.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 case=RUNTIME/'case'; manifest=json.loads((PRE/'manifest.json').read_text(encoding='utf8')); paths=list(case.glob('postProcessing/cylinderForces/*/forces.dat'))
 values=parse_forces(paths[0]) if len(paths)==1 else {}; rows=[{'time_s':k,**v} for k,v in sorted(values.items())]; advanced=next((r for r in rows if abs(float(r['time_s'])-.1025)<1e-10),None)
 quality=evaluate_quality_v4(audit_log(case/'preflight.stdout',case/'system/fvSolution'),json.loads(V4.read_text(encoding='utf8')))
 copied={f:sha(case/'0.1'/f) for f in manifest['field_hashes']}; meshphi=case/'0.1025'/'meshPhi'; uf=case/'0.1025'/'Uf'; zero=meshphi.is_file() and bool(re.search(r'internalField\s+uniform\s+0\s*;',meshphi.read_text(encoding='utf8')))
 first=float(advanced['total_N'][0]) if advanced else None
 result={'run_id':RUN,'dt_s':.0025,'duration_s':.01,'source_hashes_match':copied==manifest['field_hashes'],'first_advanced_raw_Fx_N':first,'cold_start_guard_pass':first is not None and abs(first)<=5000.,'quality_v4':quality,'Uf_reconstructed':uf.is_file(),'meshPhi_zero':zero,'force_rows':rows}
 result['PRECURSOR_CONTINUATION_PREFLIGHT']='PASS' if result['source_hashes_match'] and result['cold_start_guard_pass'] and quality['status']=='pass' and result['Uf_reconstructed'] and zero else 'FAIL'
 RESULTS.mkdir(parents=True,exist_ok=True); (RESULTS/'preflight.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8'); print(json.dumps(result,ensure_ascii=False,indent=2))
 if result['PRECURSOR_CONTINUATION_PREFLIGHT']!='PASS': raise SystemExit(1)
if __name__=='__main__': main()
