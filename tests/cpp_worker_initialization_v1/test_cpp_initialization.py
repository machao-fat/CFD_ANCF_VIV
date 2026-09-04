import json
import math
import struct
import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only"
RESULT = ROOT / "results/237_cpp_worker_initialization_v1/cpp_initialization_audit.json"


class CppInitializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = json.loads((RUN / "ancf_t0_state_cpp.json").read_text(encoding="utf-8"))
        cls.audit = json.loads(RESULT.read_text(encoding="utf-8"))

    def test_cpp_state_identity_and_finite(self):
        self.assertEqual(self.state["global_step"], 0)
        self.assertEqual(self.state["case_local_bridge_step"], 0)
        self.assertEqual(self.state["integer_tick"], 0)
        self.assertEqual(self.state["time_s"], 0.0)
        for name in ("q", "qdot", "qddot", "mass_matrix"):
            self.assertTrue(all(math.isfinite(float(value)) for value in self.state[name]))

    def test_state_hash_and_dimensions(self):
        self.assertEqual(len(self.state["q"]), 102)
        self.assertEqual(len(self.state["mass_matrix"]), 102 * 102)
        values = (self.state["q"] + self.state["qdot"] + self.state["qddot"] +
                  self.state["base_load"] + self.state["mass_matrix"])
        digest = hashlib.sha256(b"".join(struct.pack("<d", float(x)) for x in values)).hexdigest()
        self.assertEqual(digest, self.state["state_hash_sha256"])

    def test_static_equilibrium_is_qualified(self):
        self.assertTrue(self.state["equilibrated"])
        self.assertLessEqual(self.state["static_residual_inf"], 1.0e-8 * 2179104.0029808935)
        self.assertEqual(self.audit["gate"], "STAGE4F_D_CPP_WORKER_INITIALIZATION_V1_GATE: pass")
        self.assertEqual(self.audit["real_process_starts"]["MATLAB"], 0)
        self.assertEqual(self.audit["real_process_starts"]["OpenFOAM"], 0)
        self.assertEqual(self.audit["real_process_starts"]["WSL"], 0)
        self.assertEqual(self.audit["real_process_starts"]["CFD"], 0)


if __name__ == "__main__":
    unittest.main()
