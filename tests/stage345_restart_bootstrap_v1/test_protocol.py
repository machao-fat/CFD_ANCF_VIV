from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from coupling.restart_bootstrap_v1 import (  # noqa: E402
    BootstrapProtocolError,
    BootstrapSession,
    RestartBootstrapState,
    make_bootstrap_ack,
    make_bootstrap_seed,
    reject_direct_final_q,
)


ROOT = Path(__file__).resolve().parents[2]


def state() -> RestartBootstrapState:
    raw = json.loads((ROOT / "results/345_restart_bootstrap_v1/restart_bootstrap_state.json").read_text(encoding="utf-8"))
    return RestartBootstrapState.from_mapping(raw)


class RestartBootstrapProtocolTests(unittest.TestCase):
    def test_two_windows_then_ready(self):
        item = state()
        session = BootstrapSession(item, "run", "case")
        for window in (0, 1):
            seed = make_bootstrap_seed(run_id="run", case_id="case", window=window, state=item)
            session.accept_ack(make_bootstrap_ack(seed, state=item))
        session.require_ready_for_normal_continuation()
        self.assertEqual(session.accepted_windows, [0, 1])

    def test_direct_final_q_rejected(self):
        item = state()
        source = json.loads((ROOT / "runtime/stage341_dt005_long_convergence_v1/logs/structure_participant.json").read_text(encoding="utf-8"))
        with self.assertRaises(BootstrapProtocolError):
            reject_direct_final_q(source["final_q"], item)

    def test_missing_first_ack_blocks_normal(self):
        item = state()
        session = BootstrapSession(item, "run", "case")
        with self.assertRaises(BootstrapProtocolError):
            session.require_ready_for_normal_continuation()

    def test_out_of_order_ack_rejected(self):
        item = state()
        session = BootstrapSession(item, "run", "case")
        seed = make_bootstrap_seed(run_id="run", case_id="case", window=0, state=item)
        ack = make_bootstrap_ack(seed, state=item)
        with self.assertRaises(BootstrapProtocolError):
                    session.accept_ack(replace(ack, bootstrap_window=1).seal())

    def test_duplicate_ack_rejected(self):
        item = state()
        session = BootstrapSession(item, "run", "case")
        seed = make_bootstrap_seed(run_id="run", case_id="case", window=0, state=item)
        ack = make_bootstrap_ack(seed, state=item)
        session.accept_ack(ack)
        with self.assertRaises(BootstrapProtocolError):
            session.accept_ack(ack)

    def test_target_time_cannot_be_used_as_bootstrap(self):
        item = state()
        seed = make_bootstrap_seed(run_id="run", case_id="case", window=0, state=item)
        bad = replace(make_bootstrap_ack(seed, state=item), time_s=item.field_time_s + item.dt_s).seal()
        with self.assertRaises(BootstrapProtocolError):
            BootstrapSession(item, "run", "case").accept_ack(bad)

    def test_state_field_lag_contract_is_checked(self):
        item = state()
        with self.assertRaises(BootstrapProtocolError):
            BootstrapSession(replace(item, state_time_s=item.field_time_s), "run", "case")

    def test_first_window_jump_is_rejected(self):
        item = state()
        seed = make_bootstrap_seed(run_id="run", case_id="case", window=0, state=item)
        ack = make_bootstrap_ack(seed, state=item)
        bad = replace(ack, global_step=item.source_global_step + 1).seal()
        with self.assertRaises(BootstrapProtocolError):
            BootstrapSession(item, "run", "case").accept_ack(bad)

    def test_time_tick_hash_and_identity_faults_rejected(self):
        item = state()
        seed = make_bootstrap_seed(run_id="run", case_id="case", window=0, state=item)
        good = make_bootstrap_ack(seed, state=item)
        for mutation in (
            replace(good, integer_tick=good.integer_tick + 1).seal(),
            replace(good, q_sha256="0" * 64).seal(),
            replace(good, run_id="other").seal(),
            replace(good, payload_hash="0" * 64),
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(BootstrapProtocolError):
                    BootstrapSession(item, "run", "case").accept_ack(mutation)


if __name__ == "__main__":
    unittest.main()
