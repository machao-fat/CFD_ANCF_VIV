from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from coupling.multi_slice_mapping.mapping import (  # noqa: E402
    SliceDefinition,
    SliceManifest,
    ancf_hermite_H,
    convert_openfoam_force,
)
from tools.precice_ancf_adapter_v1.ancf_case_config_v1 import (  # noqa: E402
    CaseConfig,
    CaseConfigError,
)
from tools.precice_ancf_adapter_v1.ancf_generic_participant_v1 import (  # noqa: E402
    GenericANCFParticipant,
    ParticipantError,
)
from tools.precice_ancf_adapter_v1.ancf_kinematics_v1 import (  # noqa: E402
    acceleration_at_s,
    position_at_s,
    shape_matrix,
    velocity_at_s,
)


FIXTURE = Path(__file__).with_name("fixtures") / "generic_case_config_v1.json"


def raw_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_config(n: int = 3, *, section_mode: str = "explicit", base_source: str = "caller_supplied",
                kind: str = "fresh") -> CaseConfig:
    value = raw_fixture()
    value["case_identity"]["case_id"] = f"test_n_{n}"
    value["case_identity"]["run_id"] = f"run_n_{n}"
    value["section"]["mode"] = section_mode
    if section_mode == "legacy_physical":
        value["section"] = {"mode": "legacy_physical", "legacy": {
            "E_Pa": 2.0e9, "D_m": 0.05, "Di_m": 0.04, "rho_material_kg_m3": 2000.0}}
    value["base_load"]["source"] = base_source
    if base_source == "model_static":
        value["base_load"].pop("vector", None)
    slices = []
    refs = []
    for i in range(n):
        s = 10.0 * i / max(1, n - 1)
        slices.append({"slice_id": i, "s_ref_m": s, "slice_length_m": 10.0 / n, "unit_span_m": 1.0})
        refs.append([0.0, 0.0, s])
    value["coupling"]["slices"] = slices
    value["initial_state"]["reference_positions_m"] = refs
    value["initial_state"]["kind"] = kind
    if n != 5:
        q = []
        for i in range(3):
            q.extend([0.0, 0.0, 5.0 * i, 0.0, 0.0, 1.0])
        value["initial_state"]["q"] = q
        value["initial_state"]["qdot"] = [0.0] * len(q)
        value["initial_state"]["qddot"] = [0.0] * len(q)
        value["base_load"]["vector"] = [0.0] * len(q) if base_source == "caller_supplied" else None
        if base_source == "model_static":
            value["base_load"].pop("vector", None)
    return CaseConfig.from_mapping(value, base_dir=FIXTURE.parent)


class FakeBackend:
    def __init__(self, force=(2.0, 3.0, 0.0), vertex_count=2):
        self.force = tuple(force)
        self.vertex_count = vertex_count
        self.initialized = False
        self.writes = []
        self.advances = []
        self.finalized = False

    def initialize(self):
        self.initialized = True

    def write_displacement(self, payload):
        self.writes.append(payload)

    def advance(self, dt):
        self.advances.append(dt)

    def read_force(self):
        return {"force_N": self.force}

    def finalize(self):
        self.finalized = True


class EchoWorker:
    def __init__(self):
        self.requests = []

    def step(self, request):
        self.requests.append(request)
        return {"q": request.q, "qdot": request.qdot, "qddot": request.qddot}


class GenericParticipantTests(unittest.TestCase):
    def assertVectorClose(self, left, right, places=13):
        self.assertEqual(len(left), len(right))
        for a, b in zip(left, right):
            self.assertAlmostEqual(a, b, places=places)

    def test_T01_legacy_physical_config(self):
        config = make_config(section_mode="legacy_physical")
        self.assertEqual(config.kernel_model().section_property_mode, "legacy_physical")

    def test_T02_explicit_config(self):
        config = make_config()
        model = config.kernel_model()
        self.assertEqual(model.section_property_mode, "explicit")
        self.assertEqual(model.explicit_EA_N, 1413716.6941154075)

    def test_T03_caller_supplied_selection(self):
        config = make_config(base_source="caller_supplied")
        self.assertEqual(config.base_load_vector(), (0.0,) * config.ndof)
        self.assertEqual(config.kernel_model().base_load_source, "caller_supplied")

    def test_T04_model_static_selection(self):
        config = make_config(base_source="model_static")
        self.assertEqual(config.base_load_vector(), (0.0,) * config.ndof)
        self.assertEqual(config.kernel_model().base_load_source, "model_static")

    def test_T05_custom_boundary(self):
        config = make_config()
        self.assertEqual(config.boundary_arrays(), ((0, 1, 2), (0.0, 0.0, 0.0)))

    def test_T06_pinned_position_preset(self):
        value = raw_fixture()
        value["boundary"] = {"contract_id": "pinned", "preset": "pinned_position_both_ends",
                              "bottom_position_m": [0, 0, 0], "top_position_m": [0, 0, 10]}
        config = CaseConfig.from_mapping(value, base_dir=FIXTURE.parent)
        self.assertEqual(config.boundary_arrays()[0], (0, 1, 2, 12, 13, 14))

    def test_T07_fresh_dimensions(self):
        config = make_config()
        state = config.initial_state()
        self.assertEqual(len(state["q"]), config.ndof)

    def _artifact_config(self, kind):
        value = raw_fixture()
        value["initial_state"]["kind"] = kind
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            value["initial_state"]["state_file"] = "state.json"
            config = CaseConfig.from_mapping(value, base_dir=base)
            q = tuple(value["initial_state"]["q"])
            artifact = config.make_state_artifact(q, (0.0,) * config.ndof, (0.0,) * config.ndof, 7.5, 12)
            (base / "state.json").write_text(json.dumps(artifact), encoding="utf-8")
            return config, config.initial_state()

    def test_T08_prestressed_start_reset(self):
        config, state = self._artifact_config("prestressed_start")
        self.assertEqual(state["time_s"], 0.0)
        self.assertEqual(state["global_step"], 0)
        self.assertEqual(state["qdot"], (0.0,) * config.ndof)

    def test_T09_restart_preserves_time_step(self):
        config, state = self._artifact_config("restart")
        self.assertEqual(state["time_s"], 7.5)
        self.assertEqual(state["global_step"], 12)

    def test_T10_hash_key_order_stable(self):
        a = raw_fixture()
        b = json.loads(json.dumps(a))
        b["model"], b["section"] = b["section"], b["model"]
        # Restore groups while changing only insertion order inside them.
        b["model"], b["section"] = a["model"], a["section"]
        b["model"] = {key: b["model"][key] for key in reversed(list(b["model"]))}
        self.assertEqual(CaseConfig.from_mapping(a).config_sha256, CaseConfig.from_mapping(b).config_sha256)

    def test_T11_hash_changes_with_physics(self):
        a = make_config(); b = raw_fixture(); b["environment"]["gravity_m_s2"] = 10.0
        self.assertNotEqual(a.config_sha256, CaseConfig.from_mapping(b).config_sha256)

    def test_T12_interpolation_matches_canonical_mapping(self):
        config = make_config(n=3)
        q = config.initial_state()["q"]
        nodes = tuple(5.0 * i for i in range(3))
        for s in (0.0, 2.5, 5.0, 7.5, 10.0):
            ours = shape_matrix(s, 10.0, 2)
            canonical = ancf_hermite_H(s, nodes, ndof=18)
            self.assertEqual(ours, canonical)
            self.assertVectorClose(position_at_s(q, s, 10.0, 2),
                                    tuple(sum(row[j] * q[j] for j in range(18)) for row in canonical))

    def test_T13_s_zero(self):
        self.assertVectorClose(position_at_s(make_config(n=3).initial_state()["q"], 0, 10, 2), (0, 0, 0))

    def test_T14_element_boundary(self):
        q = make_config(n=3).initial_state()["q"]
        self.assertVectorClose(position_at_s(q, 5, 10, 2), (0, 0, 5))

    def test_T15_s_endpoint(self):
        q = make_config(n=3).initial_state()["q"]
        self.assertVectorClose(position_at_s(q, 10, 10, 2), (0, 0, 10))

    def test_T16_velocity_interpolation(self):
        qdot = [0.0] * 18; qdot[1] = 2.0; qdot[7] = 4.0; qdot[13] = 6.0
        self.assertVectorClose(velocity_at_s(qdot, 5.0, 10.0, 2), (0, 4, 0))
        self.assertVectorClose(acceleration_at_s([0.0] * 18, 5.0, 10.0, 2), (0, 0, 0))

    def test_T17_relative_displacement(self):
        q = make_config(n=3).initial_state()["q"]
        position = position_at_s(q, 5, 10, 2)
        self.assertEqual((position[0] - 0, position[1] - 0), (0.0, 0.0))

    def test_T18_il_cf_output(self):
        config = make_config(n=1)
        config.raw["initial_state"]["q"][0] = 0.25
        config.raw["initial_state"]["q"][1] = -0.5
        # The parser is immutable-by-convention; create the modified config.
        config = CaseConfig.from_mapping(config.raw)
        participant = GenericANCFParticipant(config, [FakeBackend()], EchoWorker())
        participant.initialize(); result = participant.step(); participant.finalize()
        self.assertEqual(result.slices[0].displacement_m, (0.25, -0.5))

    def test_T19_n_one(self):
        self.assertEqual(len(make_config(n=1).slices()), 1)

    def test_T20_n_three(self):
        self.assertEqual(len(make_config(n=3).slices()), 3)

    def test_T21_n_five(self):
        self.assertEqual(len(make_config(n=5).slices()), 5)

    def test_T22_invalid_slice_rejected(self):
        value = raw_fixture(); value["coupling"]["slices"][1]["s_ref_m"] = 0.0
        with self.assertRaises(CaseConfigError): CaseConfig.from_mapping(value)

    def test_T23_integrated_force_conversion(self):
        converted = convert_openfoam_force((2, 3, 4), 2.0, 5.0)
        self.assertEqual(converted.force_N, (5.0, 7.5, 10.0))

    def test_T24_no_second_slice_length_factor(self):
        config = make_config(n=1)
        backend = FakeBackend(force=(2.0, 3.0, 0.0))
        worker = EchoWorker(); participant = GenericANCFParticipant(config, [backend], worker)
        participant.initialize(); participant.step(); participant.finalize()
        self.assertEqual(worker.requests[0].slice_force, (20.0, 30.0, 0.0))

    def test_T25_n_slice_request_shape(self):
        config = make_config(n=5); worker = EchoWorker()
        participant = GenericANCFParticipant(config, [FakeBackend()] * 5, worker)
        participant.initialize(); participant.step(); participant.finalize()
        self.assertEqual(len(worker.requests[0].slice_force), 15)
        self.assertTrue(worker.requests[0].payload())

    def test_T26_combined_explicit_static_custom(self):
        config = make_config(n=3, base_source="model_static")
        self.assertEqual(config.kernel_model().section_property_mode, "explicit")
        self.assertEqual(config.kernel_model().base_load_source, "model_static")

    def test_T27_nonzero_damping_rejected(self):
        value = raw_fixture(); value["numerics"]["damping_alpha"] = 0.1
        with self.assertRaisesRegex(CaseConfigError, "STRUCTURAL_DAMPING"):
            CaseConfig.from_mapping(value)

    def test_T28_z_motion_rejected(self):
        value = raw_fixture(); value["coupling"]["motion_components"] = ["x", "y", "z"]
        with self.assertRaisesRegex(CaseConfigError, "UNSUPPORTED_MOTION_COMPONENT"):
            CaseConfig.from_mapping(value)

    def test_T29_state_identity_mismatch_rejected(self):
        value = raw_fixture(); value["initial_state"]["kind"] = "prestressed_start"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); value["initial_state"]["state_file"] = "state.json"
            config = CaseConfig.from_mapping(value, base_dir=base)
            artifact = config.make_state_artifact(tuple(value["initial_state"]["q"]), (0.0,) * 18, (0.0,) * 18, 0, 0)
            artifact["model_identity_sha256"] = "0" * 64
            (base / "state.json").write_text(json.dumps(artifact), encoding="utf-8")
            with self.assertRaisesRegex(CaseConfigError, "STATE_IDENTITY_FAIL"):
                config.initial_state()

    def test_T30_fake_backend_lifecycle_and_special_geometry(self):
        config = make_config(n=3); backends = [FakeBackend() for _ in range(3)]; worker = EchoWorker()
        participant = GenericANCFParticipant(config, backends, worker)
        participant.initialize(); result = participant.step(); state = participant.state_artifact(); participant.finalize()
        self.assertEqual(len(result.slices), 3)
        self.assertEqual(len(state["q"]), config.ndof)
        self.assertTrue(all(backend.writes for backend in backends))
        self.assertTrue(all(backend.finalized for backend in backends))
        # For a y-only displacement and zero x reference, the generic relative
        # contract is exactly the historical [0,y] special geometry.
        self.assertEqual(result.slices[1].displacement_m[0], 0.0)


if __name__ == "__main__":
    unittest.main()
