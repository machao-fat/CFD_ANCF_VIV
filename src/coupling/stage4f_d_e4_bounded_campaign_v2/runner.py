from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import ROOT,segment
from ..multi_slice_mapping.mapping import atomic_write_json
RESULT=ROOT/'results/58_stage4f_d_e4_bounded_campaign_v2'; CASE=ROOT/'cases/openfoam/stage4f_d_e4_bounded_campaign_v2'; RUNTIME=ROOT/'runtime/stage4f_d_e4_bounded_campaign_v2'; SOURCE=ROOT/'cases/openfoam/stage4f_d_e3_bounded_campaign_v2/block_15/checkpoints/checkpoint_step00000319_50d991755aae.json'; SOURCE_SHA='5cf040d090d1c57a4ac73cbbd7b3c59898ba1520db9aaa1b61ffaf3218323c8b'; RUN='stage58_e4_bounded_campaign_v2'; CONTRACT='cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def qualify():
 p=json.loads(SOURCE.read_text(encoding='utf-8-sig')); return {'path':str(SOURCE.resolve()),'id':p.get('checkpoint_id'),'step':p.get('step'),'time_s':p.get('time_s'),'tick':p.get('time_tick'),'sha256':sha(SOURCE),'qualified':sha(SOURCE)==SOURCE_SHA and p.get('status')=='committed' and p.get('step')==319 and p.get('time_tick')==1907500000}
def contract(): return {'run_id':RUN,'case_id':'stage58_e4_bounded_campaign_v2_3slice','dt_s':.00125,'steps':40,'blocks':4,'block_steps':10,'source':qualify(),'first_predicted_step':320,'seed_time_s':1.9075,'seed_tick':1907500000,'max_wall_clock_s':14400,'max_disk_gb':20,'stabilizer_contract_sha256':CONTRACT,'no_e3':True,'frequency_status':'not_evaluable_insufficient_cycles'}
def run():
 RESULT.mkdir(parents=True,exist_ok=True); CASE.mkdir(parents=True,exist_ok=True); RUNTIME.mkdir(parents=True,exist_ok=True); c=contract(); atomic_write_json(RESULT/'execution_contract.json',c); before=sha(SOURCE); parent=SOURCE; blocks=[]; start=time.monotonic()
 for b in range(4):
  ss=320+b*10; st=1.9075+b*10*.00125; out=segment(f'E4_STAGE58_BLOCK_{b}',RUN,c['dt_s'],ss,10,st,CASE/f'block_{b}',RUNTIME/f'block_{b}',parent); atomic_write_json(RESULT/f'block_{b}_execution.json',out); blocks.append(out)
  if out.get('fully_audited_steps')!=10 or out.get('physical_committed_steps')!=10: return {'status':'failed','blocks':blocks,'source_sha_before':before,'source_sha_after':sha(SOURCE)}
  parent=Path(out['steps'][-1]['checkpoint'])
 result={'status':'completed','blocks':blocks,'source_sha_before':before,'source_sha_after':sha(SOURCE),'wall_clock_s':time.monotonic()-start,'disk_bytes':sum(p.stat().st_size for p in CASE.rglob('*') if p.is_file())}; atomic_write_json(RESULT/'E2_execution.json',result); return result
if __name__=='__main__': print(json.dumps(run(),ensure_ascii=False))




