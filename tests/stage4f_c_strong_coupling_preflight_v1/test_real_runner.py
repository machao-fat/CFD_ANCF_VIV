from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_c_strong_coupling_preflight_v1.real_runner import main, run_three_step


class _MockCandidate:
    instances: list["_MockCandidate"] = []

    def __init__(self, plan):
        self.plan = dict(plan)
        self.root = Path(plan["case_root"])
        self.parent = Path(plan["source_checkpoint"])
        self.discarded = 0
        self.shutdowns = 0
        self.promoted = 0
        self.guess = None
        type(self).instances.append(self)

    def run_trial(self, *, previous_slice_forces_N):
        self.guess = [[float(value) for value in row] for row in previous_slice_forces_N]
        # A zero residual passes hard gates.  The coordinator still requires
        # two consecutive passes, so iteration 0 is discarded and iteration 1
        # must remain alive for in-place promotion.
        return {
            "observed_slice_forces_N": self.guess,
            "parent_checkpoint": str(self.parent),
            "parent_checkpoint_sha256": __import__("hashlib").sha256(self.parent.read_bytes()).hexdigest(),
            "max_abs_Cd": 1.0,
            "max_cfl": 0.1,
            "position_difference_over_D": 0.0,
            "velocity_difference_over_U": 0.0,
            "virtual_work_relative_error": 0.0,
            "force_conversion_relative_error": 0.0,
            "all_three_slices_complete": True,
            "log_audit": {"passed": True, "violations": []},
        }

    def discard_trial(self):
        self.discarded += 1

    def promote(self):
        self.promoted += 1
        path = self.root / "checkpoints" / f"checkpoint_step{self.plan['physical_step']:08d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"step": self.plan["physical_step"], "previous_slice_forces_N": self.guess}), encoding="utf-8")
        return path

    def shutdown(self):
        self.shutdowns += 1


class _FailingCandidate(_MockCandidate):
    def run_trial(self, *, previous_slice_forces_N):
        error = RuntimeError("slice_2 mock CFD failed")
        error.slice_id = 2
        raise error


class RealRunnerMockTests(unittest.TestCase):
    def _parent(self, root: Path) -> Path:
        parent = root / "parent.json"
        parent.write_text(json.dumps({"step": 2, "previous_slice_forces_N": [[0.0, 0.0, 0.0]] * 3}), encoding="utf-8")
        return parent

    def test_three_steps_keep_only_selected_candidate_until_promotion(self):
        _MockCandidate.instances = []
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result_root, case_root = root / "result", root / "cases"
            outcome = run_three_step(parent_checkpoint=self._parent(root), case_root=case_root, result_root=result_root, engine_factory=_MockCandidate)
            self.assertEqual(outcome["status"], "passed")
            self.assertEqual(outcome["committed_physical_steps"], 3)
            self.assertEqual(len(_MockCandidate.instances), 6)
            for first, selected in zip(_MockCandidate.instances[::2], _MockCandidate.instances[1::2]):
                self.assertEqual((first.discarded, first.promoted, first.shutdowns), (1, 0, 1))
                self.assertEqual((selected.discarded, selected.promoted, selected.shutdowns), (0, 1, 1))
            contract = json.loads((result_root / "strong_coupling_contract.json").read_text(encoding="utf-8"))
            envelope = json.loads((result_root / "execution_envelope.json").read_text(encoding="utf-8"))
            ledger = json.loads((result_root / "trial_ledger.json").read_text(encoding="utf-8"))
            registry = json.loads((result_root / "owned_process_registry.json").read_text(encoding="utf-8"))
            gates = json.loads((result_root / "gate_decisions.json").read_text(encoding="utf-8"))
            self.assertEqual(envelope["contract_sha256"], contract["contract_sha256"])
            self.assertEqual(len(ledger["trials"]), 6)
            self.assertEqual(registry["maximum_live_candidate_engines"], 1)
            self.assertEqual(len(registry["candidates"]), 6)
            self.assertEqual(sum(item["coordinator_will_promote"] for item in gates["decisions"]), 3)
            self.assertTrue(all(item["promotion"] is not None for item in envelope["steps"]))

    def test_first_failure_is_saved_and_blocks_later_steps(self):
        _FailingCandidate.instances = []
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result_root = root / "result"
            outcome = run_three_step(parent_checkpoint=self._parent(root), case_root=root / "cases", result_root=result_root, engine_factory=_FailingCandidate)
            self.assertEqual(outcome["status"], "failed")
            self.assertEqual(outcome["committed_physical_steps"], 0)
            self.assertEqual(len(outcome["steps"]), 1)
            failure = json.loads((result_root / "first_failure.json").read_text(encoding="utf-8"))
            self.assertEqual((failure["physical_step"], failure["strong_iteration"], failure["slice_id"]), (0, 0, 2))
            self.assertTrue(failure["blocks_later_physical_steps"])
            self.assertEqual(_FailingCandidate.instances[0].shutdowns, 1)

    def test_cli_never_launches_without_execute(self):
        self.assertEqual(main(["--parent-checkpoint", "parent.json"]), 0)


if __name__ == "__main__":
    unittest.main()
