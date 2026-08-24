from __future__ import annotations
import json
from ..stage4f_d_e5_staged_segment75_attempt8 import runner as impl

# The implementation is reused only as code.  All mutable execution roots and
# identity fields are replaced with a new run/case/runtime/results namespace.
impl.RESULT = impl.ROOT / "results/82_stage75_e5_candidate_1_attempt9"
impl.CASE = impl.ROOT / "cases/openfoam/stage75_e5_candidate_1_attempt9"
impl.RUNTIME = impl.ROOT / "runtime/stage75_e5_candidate_1_attempt9"
impl.RUN_ID = "stage75_e5_candidate_1_attempt9"

def run():
    return impl.run()

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
