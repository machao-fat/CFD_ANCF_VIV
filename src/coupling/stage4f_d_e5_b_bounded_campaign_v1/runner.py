from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from ..multi_slice_mapping.mapping import atomic_write_json
from ..stage4f_c_formal_abc_time_consistent_v1.runner import ROOT, segment
from ..stage4f_d_e4_campaign_orchestration_repair_v1.gate import Contract, Gate, TERMINAL

RESULT=ROOT/'results/66_stage4f_d_e5_b_bounded_campaign_v1'
CASE=ROOT/'cases/openfoam/stage4f_d_e5_b_bounded_campaign_v1'
RUNTIME=ROOT/'runtime/stage4f_d_e5_b_bounded_campaign_v1'
SOURCE=ROOT/'cases/openfoam/stage4f_d_e5_a_bounded_campaign_v1/block_3/checkpoints/checkpoint_step00000519_bb0117d44300.json'
SOURCE_SHA='1a28ffa8e4a46f112add566b9be5f3745cc318029c856db2818d541c6891ce73'
RUN_ID='stage66_e5_b_bounded_campaign_v1'; CASE_ID='stage4f_lowre_v2_1_uniform_3slice'; DT=.00125

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def qualify_source():
    x=json.loads(SOURCE.read_text(encoding='utf-8-sig')); actual=sha(SOURCE)
    return {'path':str(SOURCE.resolve()),'checkpoint_id':x.get('checkpoint_id'),'parent_checkpoint_id':x.get('parent_checkpoint_id'),'step':x.get('step'),'time_s':x.get('time_s'),'tick':x.get('time_tick'),'manifest_sha256':x.get('slice_manifest_sha256'),'config_sha256':x.get('config_sha256'),'sha256':actual,'qualified':actual==SOURCE_SHA and x.get('status')=='committed' and x.get('step')==519 and x.get('time_tick')==2157500000}
def frozen_contract():
    return Contract(run_id=RUN_ID,source_checkpoint_path=str(SOURCE.resolve()),source_checkpoint_sha256=SOURCE_SHA,source_step=519,source_tick=2157500000,source_time=2.1575,dt_global=DT,authorized_blocks=4,steps_per_block=10,authorized_steps=40,first_target_step=520,last_target_step=559,first_target_tick=2158750000,last_target_tick=2207500000,terminal_state=TERMINAL,no_auto_continuation=True,no_same_runtime_retry=True)
def execution_contract():
    c=frozen_contract(); d=json.loads(c.canonical()); d.update({'contract_sha256':c.sha256(),'case_id':CASE_ID,'source':qualify_source(),'no_cross_run_artifact_reuse':True,'next_segment_requires_new_authorization':True,'max_wall_clock_s':14400,'max_disk_bytes':20*1024**3,'stabilizer_contract_sha256':'cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78'}); return d
def run():
    RESULT.mkdir(parents=True,exist_ok=True)
    if (RESULT/'E5_B_execution.json').exists() or any(RESULT.glob('block_*_execution.json')): raise RuntimeError('same runtime retry rejected')
    CASE.mkdir(parents=True,exist_ok=False); RUNTIME.mkdir(parents=True,exist_ok=True)
    c=execution_contract()
    if not c['source']['qualified']: raise RuntimeError('source qualification failed')
    atomic_write_json(RESULT/'execution_contract.json',c); g=Gate(frozen_contract()); before=sha(SOURCE); parent=SOURCE; blocks=[]; started=time.monotonic()
    for b in range(c['first_target_step'] if isinstance(c, dict) else frozen_contract().first_target_step, (c['first_target_step'] if isinstance(c, dict) else frozen_contract().first_target_step) + 40, 10):
        block_index=(b-(c['first_target_step'] if isinstance(c, dict) else frozen_contract().first_target_step))//10
        g.begin_block(block_index); first=b; out=segment(f'E5_STAGE75_B_BLOCK_{block_index}',RUN_ID,DT,first,10,2.2075+block_index*10*DT,CASE/f'block_{block_index}',RUNTIME/f'block_{block_index}',parent); atomic_write_json(RESULT/f'block_{block_index}_execution.json',out); blocks.append(out)
        if out.get('physical_committed_steps')!=10 or out.get('fully_audited_steps')!=10: return {'status':'failed','blocks':blocks,'source_sha_before':before,'source_sha_after':sha(SOURCE)}
        for step in range(first,first+10): g.commit_step(step)
        parent=Path(out['steps'][-1]['checkpoint'])
        if block_index<3: g.next_block()
    if g.state!=TERMINAL: raise RuntimeError('terminal state not reached')
    result={'status':'completed','terminal_state':g.state,'attempted_next_block':False,'attempted_next_step':False,'blocks':blocks,'source_sha_before':before,'source_sha_after':sha(SOURCE),'wall_clock_s':time.monotonic()-started,'disk_bytes':sum(p.stat().st_size for p in CASE.rglob('*') if p.is_file())}; atomic_write_json(RESULT/'E5_B_execution.json',result); return result
if __name__=='__main__': print(json.dumps(run(),ensure_ascii=False))
