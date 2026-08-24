from __future__ import annotations

import json
from pathlib import Path

from ..stage4f_d_e5_b_bounded_campaign_v1 import runner as base

ROOT = base.ROOT
RESULT = ROOT / "results" / "72_stage4f_d_e5_b_bounded_campaign_attempt2"
CASE = ROOT / "cases" / "openfoam" / "stage4f_d_e5_b_bounded_campaign_attempt2"
RUNTIME = ROOT / "runtime" / "stage4f_d_e5_b_bounded_campaign_attempt2"
RUN_ID = "stage72_e5_b_bounded_campaign_attempt2"


def configure() -> None:
    base.RESULT = RESULT
    base.CASE = CASE
    base.RUNTIME = RUNTIME
    base.RUN_ID = RUN_ID


def run() -> dict:
    configure()
    return base.run()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
