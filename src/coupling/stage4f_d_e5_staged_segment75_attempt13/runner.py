from __future__ import annotations
import json
from ..stage4f_d_e5_staged_segment75_attempt8 import runner as impl

impl.RESULT = impl.ROOT / "results/86_stage75_e5_candidate_1_attempt13"
impl.CASE = impl.ROOT / "cases/openfoam/stage75_e5_candidate_1_attempt13"
impl.RUNTIME = impl.ROOT / "runtime/stage75_e5_candidate_1_attempt13"
impl.RUN_ID = "stage75_e5_candidate_1_attempt13"

def run():
    return impl.run()

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
