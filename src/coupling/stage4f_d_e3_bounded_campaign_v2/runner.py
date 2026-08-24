from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import ROOT,segment
from ..multi_slice_mapping.mapping import atomic_write_json
RESULT=ROOT/'results/53_stage4f_d_e3_bounded_campaign_v2'; CASE=ROOT/'cases/openfoam/stage4f_d_e3_bounded_campaign_v2'; RUNTIME=ROOT/'runtime/stage4f_d_e3_bounded_campaign_v2'; SOURCE=ROOT/'cases/openfoam/stage4f_d_e2_bounded_pilot_v2/block_7/checkpoints/checkpoint_step00000159_883464ad4ea1.json'; SOURCE_SHA='66f151394af7626ae937174054695bd1a435dfcad01e1e65595eb641e81cd6eb'; RUN='stage53_e3_bounded_campaign_v2'; CONTRACT='cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def qualify():
 p=json.loads(SOURCE.read_text(encoding='utf-8-sig')); return {'path':str(SOURCE.resolve()),'id':p.get('checkpoint_id'),'step':p.get('step'),'time_s':p.get('time_s'),'tick':p.get('time_tick'),'sha256':sha(SOURCE),'qualified':sha(SOURCE)==SOURCE_SHA and p.get('status')=='committed' and p.get('step')==159 and p.get('time_tick')==1707500000}
def contract(): return {'run_id':RUN,'case_id':'stage52_e3_bounded_campaign_v1_3slice','dt_s':.00125,'steps':160,'blocks':16,'block_steps':10,'source':qualify(),'first_predicted_step':160,'seed_time_s':1.7075,'seed_tick':1707500000,'max_wall_clock_s':14400,'max_disk_gb':20,'stabilizer_contract_sha256':CONTRACT,'no_e3':False,'frequency_status':'not_evaluable_insufficient_cycles'}
def run():
 RESULT.mkdir(parents=True,exist_ok=True); CASE.mkdir(parents=True,exist_ok=True); RUNTIME.mkdir(parents=True,exist_ok=True); c=contract(); atomic_write_json(RESULT/'execution_contract.json',c); before=sha(SOURCE); parent=SOURCE; blocks=[]; start=time.monotonic()
 for b in range(16):
  ss=160+b*10; st=1.7075+b*10*.00125; out=segment(f'E3_STAGE52_BLOCK_{b}',RUN,c['dt_s'],ss,10,st,CASE/f'block_{b}',RUNTIME/f'block_{b}',parent); atomic_write_json(RESULT/f'block_{b}_execution.json',out); blocks.append(out)
  if out.get('fully_audited_steps')!=10 or out.get('physical_committed_steps')!=10: return {'status':'failed','blocks':blocks,'source_sha_before':before,'source_sha_after':sha(SOURCE)}
  parent=Path(out['steps'][-1]['checkpoint'])
 result={'status':'completed','blocks':blocks,'source_sha_before':before,'source_sha_after':sha(SOURCE),'wall_clock_s':time.monotonic()-start,'disk_bytes':sum(p.stat().st_size for p in CASE.rglob('*') if p.is_file())}; atomic_write_json(RESULT/'E2_execution.json',result); return result
if __name__=='__main__': print(json.dumps(run(),ensure_ascii=False))
