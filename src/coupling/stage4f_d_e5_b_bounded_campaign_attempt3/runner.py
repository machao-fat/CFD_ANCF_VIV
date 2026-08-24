from __future__ import annotations
import json
from ..stage4f_d_e5_b_bounded_campaign_v1 import runner as base

ROOT = base.ROOT
RESULT = ROOT / "results/74_stage4f_d_e5_b_bounded_campaign_attempt3"
CASE = ROOT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3"
RUNTIME = ROOT / "runtime/stage4f_d_e5_b_bounded_campaign_attempt3"
RUN_ID = "stage74_e5_b_bounded_campaign_attempt3"

def configure():
    base.RESULT, base.CASE, base.RUNTIME, base.RUN_ID = RESULT, CASE, RUNTIME, RUN_ID

def run():
    configure()
    return base.run()

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
