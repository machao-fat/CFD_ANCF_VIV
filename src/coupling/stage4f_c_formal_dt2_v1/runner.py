from pathlib import Path
from ..stage4f_c_formal_abc_time_consistent_v1.runner import segment, ROOT
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1 import probe as base
from ..multi_slice_mapping.mapping import atomic_write_json

RESULT = ROOT / 'results/33_stage4f_c_formal_dt2_v1'
RUN_ID = 'stage33_formal_C_dt2_v1'

def run():
    case = ROOT / 'cases/openfoam/stage4f_c_formal_dt2_v1/C'
    runtime = ROOT / 'runtime/stage4f_c_formal_dt2_v1/C'
    out = segment('C', RUN_ID, 0.00125, 0, 40, base.START, case, runtime, base.PARENT)
    atomic_write_json(RESULT / 'C_execution.json', out)
    return out

if __name__ == '__main__':
    print(run())
