from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import segment,ROOT,RESULT as BASE_RESULT
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1 import probe as base
from ..stage4f_c_utf8_checkpoint_reader_repair_v1.utf8 import read_json
from ..multi_slice_mapping.mapping import atomic_write_json
RESULT=ROOT/'results/31_stage4f_c_restart_step_identity_repair_v1'
RUN_ID='stage31_formal_B_restart_time_consistent_v1'
def run():
 first_case=ROOT/'cases/openfoam/stage4f_c_restart_step_identity_repair_v1/B_first'; first_runtime=ROOT/'runtime/stage4f_c_restart_step_identity_repair_v1/B_first'
 first=segment('B_first',RUN_ID,.0025,0,5,base.START,first_case,first_runtime,base.PARENT); atomic_write_json(RESULT/'B_first_execution.json',first)
 if first.get('fully_audited_steps')!=5:return {'status':'failed','B_first':first,'B_restart':None}
 source=Path(first['steps'][-1]['checkpoint']); source_cp=read_json(source)
 if source_cp.get('step')!=4 or source_cp.get('time_tick')!=1520000000: raise RuntimeError('source checkpoint step/tick mismatch')
 restart_case=ROOT/'cases/openfoam/stage4f_c_restart_step_identity_repair_v1/B_restart'; restart=segment('B_restart',RUN_ID,.0025,5,15,1.52,restart_case,ROOT/'runtime/stage4f_c_restart_step_identity_repair_v1/B_restart',source);atomic_write_json(RESULT/'B_restart_execution.json',restart)
 result={'status':'accepted' if restart.get('fully_audited_steps')==15 else 'failed','B_first':first,'B_restart':restart,'source_checkpoint':str(source),'source_step':4,'first_restart_step':5};atomic_write_json(RESULT/'stage31_execution.json',result);return result
