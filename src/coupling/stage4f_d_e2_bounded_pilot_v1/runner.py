from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import ROOT,segment
from ..multi_slice_mapping.mapping import atomic_write_json
RESULT=ROOT/'results/45_stage4f_d_e2_bounded_pilot_v1'; CASE=ROOT/'cases/openfoam/stage4f_d_e2_bounded_pilot_v1'; RUNTIME=ROOT/'runtime/stage4f_d_e2_bounded_pilot_v1'
SOURCE=ROOT/'cases/openfoam/stage4f_d_e1_bounded_pilot_v1/block_3/checkpoints/checkpoint_step00000079_e19d01431943.json'; SOURCE_SHA='e14a0552ec6230328208ca1a4a3aafe3e9fb2154a753226c1d93fbba8aa49243'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def qualify():
 p=json.loads(SOURCE.read_text(encoding='utf-8-sig')); ok=SOURCE.exists() and sha(SOURCE)==SOURCE_SHA and p.get('transaction_state')=='committed' and p.get('status')=='committed'
 return {'qualified':ok,'path':str(SOURCE.resolve()),'id':p.get('checkpoint_id'),'sha256':sha(SOURCE),'size':SOURCE.stat().st_size,'mtime_ns':SOURCE.stat().st_mtime_ns,'step':p.get('step'),'time_s':p.get('time_s'),'tick':p.get('time_tick'),'schema':p.get('schema_version'),'parent':p.get('parent_checkpoint_id'),'config_sha256':p.get('config_sha256'),'tau':p.get('stabilizer_state',{}).get('tau_decimal'),'transaction_state':p.get('transaction_state')}
def contract():
 q=qualify(); return {'source':q,'dt_s':.00125,'steps':80,'blocks':8,'block_steps':10,'start_time_s':1.6075,'end_time_s':1.7075,'start_tick':1607500000,'end_tick':1707500000,'max_wall_clock_s':14400,'max_disk_gb':20,'run_id':'stage45_e2_bounded_pilot_v1','case_id':'stage4f_lowre_v2_1_uniform_3slice','no_e3':True,'no_five_nine_slice':True,'frequency_status':'not_evaluable_insufficient_cycles'}
def run():
 RESULT.mkdir(parents=True,exist_ok=True); CASE.mkdir(parents=True,exist_ok=False); RUNTIME.mkdir(parents=True,exist_ok=False); c=contract(); atomic_write_json(RESULT/'execution_contract.json',c)
 if not c['source']['qualified']: return {'status':'source_failed','blocks':[]}
 orig=sha(SOURCE); start=time.monotonic(); parent=SOURCE; blocks=[]
 for bidx in range(8):
  if time.monotonic()-start>=c['max_wall_clock_s']: return {'status':'budget_stopped','blocks':blocks}
  used=sum(p.stat().st_size for p in CASE.rglob('*') if p.is_file())
  if used>=c['max_disk_gb']*1024**3: return {'status':'budget_stopped','blocks':blocks}
  b=segment(f'E2_BLOCK_{bidx}',c['run_id'],c['dt_s'],40+bidx*10,10,1.6075+bidx*.0125,CASE/f'block_{bidx}',RUNTIME/f'block_{bidx}',parent); atomic_write_json(RESULT/f'block_{bidx}_execution.json',b); blocks.append(b)
  if b.get('fully_audited_steps')!=10 or b.get('physical_committed_steps')!=10: return {'status':'failed','blocks':blocks}
  parent=Path(b['steps'][-1]['checkpoint'])
  if sha(SOURCE)!=orig: return {'status':'source_mutated','blocks':blocks}
 out={'status':'completed','blocks':blocks,'source_sha_before':orig,'source_sha_after':sha(SOURCE),'wall_clock_s':time.monotonic()-start,'disk_bytes':sum(p.stat().st_size for p in CASE.rglob('*') if p.is_file())}; atomic_write_json(RESULT/'E2_execution.json',out); return out
if __name__=='__main__': run()
