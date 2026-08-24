from ..stage4f_c_formal_abc_time_consistent_v1.runner import segment, ROOT
from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1 import probe as base
from ..multi_slice_mapping.mapping import atomic_write_json
from .ownership import prepare_stage_parent, validate_factory_target

RESULT = ROOT / 'results/34_stage4f_c_case_initialization_repair_v1'
RUN_ID = 'stage34_formal_C_case_owner_v1'


def run():
    case_parent = ROOT / 'cases/openfoam/stage4f_c_case_initialization_repair_v1'
    runtime_parent = ROOT / 'runtime/stage4f_c_case_initialization_repair_v1'
    case = case_parent / 'C'
    runtime = runtime_parent / 'C'
    prepare_stage_parent(case_parent)
    prepare_stage_parent(runtime_parent)
    validate_factory_target(case_parent, case)
    validate_factory_target(runtime_parent, runtime)
    out = segment('C', RUN_ID, 0.00125, 0, 40, base.START, case, runtime, base.PARENT)
    atomic_write_json(RESULT / 'C_execution.json', out)
    return out


if __name__ == '__main__':
    print(run())
