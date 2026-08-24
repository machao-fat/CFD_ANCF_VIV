from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import ROOT, segment
from ..multi_slice_mapping.mapping import atomic_write_json
RESULT=ROOT/'results/46_stage4f_d_e2_motion_initialization_repair_v1'; CASE=ROOT/'cases/openfoam/stage4f_d_e2_motion_initialization_repair_v1'; RUNTIME=ROOT/'runtime/stage4f_d_e2_motion_initialization_repair_v1'
SOURCE=ROOT/'cases/openfoam/stage4f_d_e1_bounded_pilot_v1/block_3/checkpoints/checkpoint_step00000079_e19d01431943.json'; SOURCE_SHA='e14a0552ec6230328208ca1a4a3aafe3e9fb2154a753226c1d93fbba8aa49243'; CONTRACT_SHA='cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def qualify():
 p=json.loads(SOURCE.read_text(encoding='utf-8-sig')); return {'qualified':SOURCE.exists() and sha(SOURCE)==SOURCE_SHA and p.get('status')=='committed' and p.get('step')==79 and p.get('time_tick')==1607500000 and abs(float(p.get('time_s'))-1.6075)<1e-12,'path':str(SOURCE.resolve()),'id':p.get('checkpoint_id'),'sha256':sha(SOURCE),'size':SOURCE.stat().st_size,'mtime_ns':SOURCE.stat().st_mtime_ns,'step':p.get('step'),'time_s':p.get('time_s'),'tick':p.get('time_tick'),'run_id':p.get('run_id'),'case_id':p.get('case_id'),'branch':p.get('branch'),'contract_sha256':p.get('stabilizer_state',{}).get('contract_sha256')}
def contract(): return {'source':qualify(),'source_step':79,'seed_time_s':1.6075,'seed_tick':1607500000,'first_predicted_step':80,'dt_s':.00125,'steps':80,'blocks':8,'block_steps':10,'start_time_s':1.6075,'end_time_s':1.7075,'start_tick':1607500000,'end_tick':1707500000,'max_wall_clock_s':14400,'max_disk_gb':20,'run_id':'stage46_e2_motion_repair_v1','case_id':'stage46_e2_motion_repair_v1_3slice','stabilizer_contract_sha256':CONTRACT_SHA,'no_e3':True,'frequency_status':'not_evaluable_or_diagnostic_by_frozen_contract'}
def run():
 RESULT.mkdir(parents=True,exist_ok=True); CASE.mkdir(parents=True,exist_ok=True); RUNTIME.mkdir(parents=True,exist_ok=True); c=contract(); atomic_write_json(RESULT/'execution_contract.json',c)
 if not c['source']['qualified']: return {'status':'source_failed','blocks':[]}
 before=sha(SOURCE); start=time.monotonic(); parent=SOURCE; blocks=[]
 for bidx in range(8):
  if time.monotonic()-start>=c['max_wall_clock_s']: return {'status':'budget_stopped','blocks':blocks}
  ss=c['first_predicted_step']+bidx*c['block_steps']; st=c['seed_time_s']+bidx*c['block_steps']*c['dt_s']
  out=segment(f'E2_REPAIR_BLOCK_{bidx}',c['run_id'],c['dt_s'],ss,c['block_steps'],st,CASE/f'block_{bidx}',RUNTIME/f'block_{bidx}',parent); atomic_write_json(RESULT/f'block_{bidx}_execution.json',out); blocks.append(out)
  if out.get('fully_audited_steps')!=c['block_steps'] or out.get('physical_committed_steps')!=c['block_steps']: return {'status':'failed','blocks':blocks,'source_sha_before':before,'source_sha_after':sha(SOURCE)}
  parent=Path(out['steps'][-1]['checkpoint'])
 result={'status':'completed','blocks':blocks,'source_sha_before':before,'source_sha_after':sha(SOURCE),'wall_clock_s':time.monotonic()-start,'disk_bytes':sum(p.stat().st_size for p in CASE.rglob('*') if p.is_file())}; atomic_write_json(RESULT/'E2_execution.json',result); return result
if __name__=='__main__': run()
