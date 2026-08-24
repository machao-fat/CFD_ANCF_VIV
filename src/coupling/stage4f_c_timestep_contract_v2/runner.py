from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import segment, ROOT
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1 import probe as base
from ..multi_slice_mapping.mapping import atomic_write_json

RESULT = ROOT / 'results/37_stage4f_c_timestep_contract_v2'
RUN_ID = 'stage37_dt125_restart_v1'

def run():
    parent = ROOT / 'cases/openfoam/stage4f_c_timestep_contract_v2'
    runtime_parent = ROOT / 'runtime/stage4f_c_timestep_contract_v2'
    parent.mkdir(parents=True, exist_ok=True); runtime_parent.mkdir(parents=True, exist_ok=True)
    first_case, first_runtime = parent / 'first10', runtime_parent / 'first10'
    if first_case.exists() or first_runtime.exists(): raise FileExistsError('first10 target exists')
    first = segment('B_first', RUN_ID, 0.00125, 0, 10, base.START, first_case, first_runtime, base.PARENT)
    atomic_write_json(RESULT / 'B_first10_execution.json', first)
    if first.get('fully_audited_steps') != 10: return {'status':'failed','first':first}
    source = Path(first['steps'][-1]['checkpoint'])
    restart_case, restart_runtime = parent / 'restart30', runtime_parent / 'restart30'
    if restart_case.exists() or restart_runtime.exists(): raise FileExistsError('restart30 target exists')
    second = segment('B_restart', RUN_ID, 0.00125, 10, 30, 1.52, restart_case, restart_runtime, source)
    atomic_write_json(RESULT / 'B_restart30_execution.json', second)
    out={'status':'accepted' if second.get('fully_audited_steps')==30 else 'failed','first':first,'restart':second,'source_checkpoint':str(source)}
    atomic_write_json(RESULT / 'restart_execution.json', out); return out
