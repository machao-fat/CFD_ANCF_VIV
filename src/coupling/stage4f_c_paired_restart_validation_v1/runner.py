from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import segment, ROOT
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1 import probe as base
from ..multi_slice_mapping.mapping import atomic_write_json
RESULT=ROOT/'results/39_stage4f_c_paired_restart_validation_v1'; RUN='stage39_paired_dt125_v1'
def run():
    root=ROOT/'cases/openfoam/stage4f_c_paired_restart_validation_v1'; rt=ROOT/'runtime/stage4f_c_paired_restart_validation_v1'; root.mkdir(parents=True,exist_ok=True); rt.mkdir(parents=True,exist_ok=True)
    pref=segment('PREFIX',RUN,.00125,0,10,base.START,root/'prefix',rt/'prefix',base.PARENT); atomic_write_json(RESULT/'prefix_execution.json',pref)
    if pref.get('fully_audited_steps')!=10:return {'status':'failed','prefix':pref}
    source=Path(pref['steps'][-1]['checkpoint']); cont=segment('CONT',RUN,.00125,10,30,1.52,root/'cont',rt/'cont',source); atomic_write_json(RESULT/'cont_execution.json',cont)
    rest=segment('REST',RUN,.00125,10,30,1.52,root/'rest',rt/'rest',source); atomic_write_json(RESULT/'rest_execution.json',rest)
    out={'status':'accepted' if cont.get('fully_audited_steps')==30 and rest.get('fully_audited_steps')==30 else 'failed','prefix':pref,'cont':cont,'rest':rest,'source_checkpoint':str(source)}; atomic_write_json(RESULT/'paired_execution.json',out); return out
