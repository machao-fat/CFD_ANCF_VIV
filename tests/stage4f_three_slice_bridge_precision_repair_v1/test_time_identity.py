import json
import math
import unittest
from src.coupling.stage4f_three_slice_bridge_precision_repair_v1.time_identity import *

class TestTimeIdentity(unittest.TestCase):
    kw = dict(expected_step=1, expected_time_s="1.508125", case_id="case", slice_id=2, run_id="run")
    def test_round_trip_and_distinct_truncation(self):
        x = identity(global_step=1, time_s="1.508125", case_id="case", slice_id=2, run_id="run")
        self.assertEqual(parse_and_validate(dumps(x), **self.kw), x)
        bad = dict(x, time_s="1.50813", time_tick=time_to_tick("1.50813"))
        with self.assertRaisesRegex(TimeIdentityError, "time_tick|time_s"):
            parse_and_validate(dumps(bad), **self.kw)
    def test_dt_values_and_json_forms(self):
        for dt in ("0.0025", "0.00125", "0.000625"):
            t = Decimal("1.5075") + Decimal(dt)
            x = identity(global_step=0, time_s=t, case_id="c", slice_id=0, run_id="r")
            self.assertEqual(time_to_tick(x["time_s"]), x["time_tick"])
            self.assertEqual(parse_and_validate(json.dumps(x), expected_step=0, expected_time_s=t, case_id="c", slice_id=0, run_id="r"), x)
    def test_reject_identity_and_nonfinite(self):
        x = identity(global_step=1, time_s="1.508125", case_id="case", slice_id=2, run_id="run")
        for key, value in (("global_step", 2), ("slice_id", 1), ("run_id", "old")):
            with self.subTest(key=key), self.assertRaises(TimeIdentityError):
                parse_and_validate(dumps(dict(x, **{key:value})), **self.kw)
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaises(TimeIdentityError): time_to_tick(value)
    def test_old_marker_and_continuity(self):
        old = '{"kind":"motion_consumed","step":1,"time_s":1.50813}'
        self.assertNotEqual(legacy_marker_status(old, **self.kw), "accepted")
        a = identity(global_step=1, time_s="1.508125", case_id="case", slice_id=0, run_id="run")
        b = identity(global_step=2, time_s="1.50875", case_id="case", slice_id=0, run_id="run")
        self.assertEqual(b["time_tick"] - a["time_tick"], 625000)

if __name__ == "__main__": unittest.main()
