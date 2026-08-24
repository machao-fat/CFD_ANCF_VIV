from __future__ import annotations
import hashlib, json, shutil, time
from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import ROOT, segment
from ..multi_slice_mapping.mapping import atomic_write_json

RESULT=ROOT/'results/42_stage4f_d_e1_bounded_pilot_v1'
CASE=ROOT/'cases/openfoam/stage4f_d_e1_bounded_pilot_v1'
RUNTIME=ROOT/'runtime/stage4f_d_e1_bounded_pilot_v1'
STAGE41=ROOT/'results/41_stage4f_d_extended_transient_entry_design_v1/recommended_pilot_contract.json'
SOURCE=ROOT/'cases/openfoam/stage4f_c_case_initialization_repair_v1/C/checkpoints/checkpoint_step00000039_c55bb68c7361.json'
SOURCE_SHA='a944a040c0fbfcd560a36fcf185cd422262c6091e98bb9f50af19aaa2f58965c'

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def qualify_source():
    p=json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    committed=p.get('transaction_state')=='committed' and p.get('status')=='committed'
    return {'qualified':SOURCE.exists() and sha(SOURCE)==SOURCE_SHA and committed,
      'canonical_path':str(SOURCE.resolve()),'checkpoint_id':'step00000039_c55bb68c7361','sha256':sha(SOURCE),
      'size':SOURCE.stat().st_size,'mtime_ns':SOURCE.stat().st_mtime_ns,'schema':p.get('schema'),
      'global_step':p.get('step'),'integer_tick':p.get('time_tick'),'physical_time_s':p.get('time_s'),'state_role':p.get('transaction_state')}

def execution_contract():
    frozen=json.loads(STAGE41.read_text(encoding='utf-8'))
    if frozen['dt_s']!=.00125 or frozen['global_steps']!=40 or frozen['block_length_steps']!=10: raise ValueError('Stage41 contract mismatch')
    q=qualify_source()
    return {'source':q,'dt_s':frozen['dt_s'],'steps':40,'blocks':4,'block_steps':10,
      'start_time_s':1.5575,'end_time_s':1.6075,'start_tick':1557500000,'end_tick':1607500000,
      'max_wall_clock_s':frozen['max_wall_clock_s'],'max_disk_gb':frozen['max_disk_gb'],'no_step_41':True}

def run():
    RESULT.mkdir(parents=True,exist_ok=True); CASE.mkdir(parents=True,exist_ok=False); RUNTIME.mkdir(parents=True,exist_ok=False)
    contract=execution_contract(); atomic_write_json(RESULT/'execution_contract.json',contract)
    if not contract['source']['qualified']: return {'status':'source_failed','blocks':[]}
    original=sha(SOURCE); started=time.monotonic(); blocks=[]; parent=SOURCE
    for block in range(4):
        if time.monotonic()-started>=contract['max_wall_clock_s']: return {'status':'budget_stopped','blocks':blocks}
        used=sum(p.stat().st_size for p in CASE.rglob('*') if p.is_file())
        if used>=contract['max_disk_gb']*1024**3: return {'status':'budget_stopped','blocks':blocks}
        step=40+block*10; t=1.5575+block*.0125
        b=segment(f'E1_BLOCK_{block}','stage42_e1_bounded_v1',.00125,step,10,t,CASE/f'block_{block}',RUNTIME/f'block_{block}',parent)
        atomic_write_json(RESULT/f'block_{block}_execution.json',b); blocks.append(b)
        if b.get('fully_audited_steps')!=10 or b.get('physical_committed_steps')!=10: return {'status':'failed','blocks':blocks}
        parent=Path(b['steps'][-1]['checkpoint'])
        if sha(SOURCE)!=original: return {'status':'source_mutated','blocks':blocks}
    out={'status':'completed','blocks':blocks,'source_sha_before':original,'source_sha_after':sha(SOURCE),'wall_clock_s':time.monotonic()-started,
      'disk_bytes':sum(p.stat().st_size for p in CASE.rglob('*') if p.is_file())}
    atomic_write_json(RESULT/'E1_execution.json',out); return out

if __name__=='__main__': run()
