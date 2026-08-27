from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coupling.precice_adapter_v1 import PreciceBackendError, PrecicePythonBackend


class FakeParticipant:
    def __init__(self, *args):
        self.args = args
        self.calls = []
        self.ids = [10, 11]

    def set_mesh_vertices(self, mesh, vertices):
        self.calls.append(("vertices", mesh, vertices))
        return self.ids

    def initialize(self): self.calls.append(("initialize",)); return 0.00125
    def write_data(self, *args): self.calls.append(("write",) + args)
    def advance(self, dt): self.calls.append(("advance", dt))
    def read_data(self, *args): self.calls.append(("read",) + args); return [[1.0, 2.0], [3.0, 4.0]]
    def finalize(self): self.calls.append(("finalize",))


class BackendTests(unittest.TestCase):
    def make_backend(self, factory):
        temp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
        temp.write(b"<precice-configuration/>")
        temp.close()
        return PrecicePythonBackend(
            "ANCF", Path(temp.name), "Structure", "Displacement", "Force",
            [(0.0, 0.0), (1.0, 0.0)], participant_factory=factory), temp.name

    def test_full_backend_lifecycle_uses_pyprecice3_calls(self):
        fake = FakeParticipant()
        backend, path = self.make_backend(lambda *args: fake)
        try:
            backend.initialize()
            backend.write_displacement({"displacement_m": [[0.0, 0.0], [0.1, 0.2]]})
            backend.advance(0.00125)
            self.assertEqual(backend.read_force(), {"force_N": [[1.0, 2.0], [3.0, 4.0]]})
            backend.finalize()
            self.assertEqual([c[0] for c in fake.calls], ["vertices", "initialize", "write", "advance", "read", "finalize"])
        finally:
            Path(path).unlink(missing_ok=True)

    def test_invalid_config_and_payload_fail_closed(self):
        with self.assertRaises(PreciceBackendError):
            PrecicePythonBackend("ANCF", "missing.xml", "Structure", "D", "F", [(0.0, 0.0)])
        backend, path = self.make_backend(FakeParticipant)
        try:
            backend.initialize()
            with self.assertRaises(PreciceBackendError):
                backend.write_displacement({})
        finally:
            Path(path).unlink(missing_ok=True)

        malformed = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
        malformed.write(b"<precice>")
        malformed.close()
        try:
            with self.assertRaises(PreciceBackendError):
                PrecicePythonBackend("ANCF", malformed.name, "Structure", "D", "F", [(0.0, 0.0)])
        finally:
            Path(malformed.name).unlink(missing_ok=True)

    def test_factory_failure_is_wrapped_and_no_fallback(self):
        backend, path = self.make_backend(lambda *args: (_ for _ in ()).throw(RuntimeError("disconnect")))
        try:
            with self.assertRaises(PreciceBackendError):
                backend.initialize()
            self.assertIsNone(backend._participant)
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
