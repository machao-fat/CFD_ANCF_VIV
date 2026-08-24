from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import segment, ROOT
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1 import probe as base
from ..multi_slice_mapping.mapping import atomic_write_json

RESULT = ROOT / 'results/36_stage4f_c_dt4_asymptotic_diagnostic_v1'
RUN_ID = 'stage36_dt4_diagnostic_v1'

def run():
    parent = ROOT / 'cases/openfoam/stage4f_c_dt4_asymptotic_diagnostic_v1'
    runtime_parent = ROOT / 'runtime/stage4f_c_dt4_asymptotic_diagnostic_v1'
    parent.mkdir(parents=True, exist_ok=True)
    runtime_parent.mkdir(parents=True, exist_ok=True)
    case = parent / 'D'; runtime = runtime_parent / 'D'
    if case.exists() or runtime.exists():
        raise FileExistsError('Stage 36 factory-owned D target already exists')
    out = segment('D', RUN_ID, 0.000625, 0, 80, base.START, case, runtime, base.PARENT)
    atomic_write_json(RESULT / 'D_execution.json', out)
    return out
