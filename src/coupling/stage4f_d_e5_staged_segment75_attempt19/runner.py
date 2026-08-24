from __future__ import annotations
import json
from ..stage4f_d_e5_staged_segment75_attempt8 import runner as impl

impl.RESULT = impl.ROOT / "results/92_stage75_e5_candidate_1_attempt19"
impl.CASE = impl.ROOT / "cases/openfoam/stage75_e5_candidate_1_attempt19"
impl.RUNTIME = impl.ROOT / "runtime/stage75_e5_candidate_1_attempt19"
impl.RUN_ID = "stage75_e5_candidate_1_attempt19"

def run():
    return impl.run()

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
