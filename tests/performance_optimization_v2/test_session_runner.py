from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from coupling.performance_optimization_v2.contracts import BenchmarkContract
from coupling.performance_optimization_v2.session_runner import BenchmarkSessionRunner
from coupling.performance_optimization_v2.matlab_persistent import PersistentMatlabError, PersistentMatlabRunner


class SessionRunnerTests(unittest.TestCase):
    def contract(self, root: Path, factors: tuple[str, ...] = ()) -> dict:
        label = "_".join(factors) or "B"
        runtime = root / "runtime" / "benchmarks" / label
        token = uuid.uuid4().hex[:8]
        return BenchmarkContract("stage95", f"run95_{label}_{token}", f"case95_{label}_{token}", runtime, root / "source.mat", 559, 2.2075, 2207500000, factors=factors).to_dict()

    def test_offline_accept_does_not_launch(self):
        root = Path("D:/stage95-project"); runtime = root / "runtime"
        runner = BenchmarkSessionRunner(project_root=root, runtime=runtime, launcher=lambda *a, **k: self.fail("launch"))
        from coupling.performance_optimization_v2.contracts import canonical_bytes
        contract = self.contract(root); inbox = runtime / "inbox" / "run95_b.json"; inbox.write_bytes(canonical_bytes(contract))
        result = runner.accept(inbox, launch_matlab=False)
        self.assertEqual(result["external_process_starts"], 0)

    def test_openfoam_factor_is_rejected_before_launch(self):
        root = Path("D:/stage95-project2"); runtime = root / "runtime"
        runner = BenchmarkSessionRunner(project_root=root, runtime=runtime, launcher=lambda *a, **k: self.fail("launch"))
        from coupling.performance_optimization_v2.contracts import canonical_bytes
        contract = self.contract(root, ("O",)); inbox = runtime / "inbox" / "run95_o.json"; inbox.write_bytes(canonical_bytes(contract))
        result = runner.accept(inbox, launch_matlab=True)
        self.assertEqual(result["state"], "FAILED_TERMINAL")

    def test_explicit_coordinator_is_the_only_o_path(self):
        root = Path("D:/stage95-project3"); runtime = root / "runtime"; launched = []
        class Proc:
            pid = 9200
            returncode = 0
            def terminate(self): pass
            def wait(self, timeout=None): return 0
            def poll(self): return 0
        def launcher(command, **kwargs): launched.append((command, kwargs)); return Proc()
        runner = BenchmarkSessionRunner(project_root=root, runtime=runtime, launcher=launcher)
        from coupling.performance_optimization_v2.contracts import canonical_bytes
        contract = self.contract(root, ("O",)); contract["coordinator_command"] = ["python", "coordinator.py"]
        import hashlib, json
        payload = {key: value for key, value in contract.items() if key != "contract_sha256"}
        contract["contract_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
        inbox = runtime / "inbox" / "run95_o_coordinator.json"; inbox.write_bytes(canonical_bytes(contract))
        result = runner.accept(inbox, launch_matlab=True)
        self.assertEqual(result["state"], "BENCHMARK_COORDINATOR_RUNNING"); self.assertEqual(launched[0][0], ["python", "coordinator.py"])
        runner.stop()

    def test_persistent_matlab_requires_fresh_native_resume(self):
        runner = PersistentMatlabRunner(work_dir=Path("D:/stage95-matlab/work"), runtime=Path("D:/stage95-matlab/runtime"),
            manifest=None, run_id="run95-m", case_id="case95-m", source_global_step=559,
            source_time_s=2.2075, source_tick=2207500000, native_resume=None)
        with self.assertRaises(PersistentMatlabError): runner.start()


if __name__ == "__main__": unittest.main()
