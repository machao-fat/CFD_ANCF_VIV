"""M2 SHM1 model/config/wire contract tests.

The C++ worker round-trip portion is enabled by setting
``CFD_ANCF_ANCF_WORKER_BINARY`` to the freshly built ANCF worker.  It is kept
out of the ordinary Python-only test environment because it deliberately
executes the isolated local test binary.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (  # noqa: E402
    KernelModel,
    KernelStepRequest,
    SpanwiseHydrodynamicRegion,
    SPANWISE_HYDRODYNAMIC_EXTENSION_MARKER,
    SPANWISE_HYDRODYNAMIC_EXTENSION_VERSION,
    DAMPING_EXTENSION_MARKER,
    decode_kernel_response,
    encode_kernel_request,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import (  # noqa: E402
    HEADER,
    MESSAGE_INITIALIZE,
    MESSAGE_INITIALIZE_ACK,
    MESSAGE_SHUTDOWN,
    encode_control,
)
from tools.precice_ancf_adapter_v1.ancf_case_config_v1 import (  # noqa: E402
    CaseConfig,
    CaseConfigError,
)

FIXTURE = Path(__file__).with_name("fixtures") / "generic_case_config_v1.json"
SHM1 = struct.pack("<I", SPANWISE_HYDRODYNAMIC_EXTENSION_MARKER)


def raw_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def region(left: float = 1.0, right: float = 4.0, *, mass=(1.0, 2.0, 0.0),
           damping=(3.0, 4.0, 0.0)) -> dict:
    return {
        "s_min_m": left,
        "s_max_m": right,
        "added_mass_per_length_kg_m": list(mass),
        "linear_damping_per_length_Ns_m2": list(damping),
    }


def config_with_regions(regions: list[dict], *, damping: dict | None = None) -> CaseConfig:
    value = raw_fixture()
    value["model"]["hydrodynamic_regions"] = regions
    if damping is not None:
        value["damping"] = damping
    return CaseConfig.from_mapping(value, base_dir=FIXTURE.parent)


def read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    while size:
        chunk = stream.read(size)
        if not chunk:
            break
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)


class SpanwiseHydrodynamicModelTests(unittest.TestCase):
    def test_A_legacy_bytes_preserved_without_shm1(self):
        model = raw_fixture()
        config = CaseConfig.from_mapping(model, base_dir=FIXTURE.parent)
        wire_model = config.kernel_model()
        historical = wire_model.bytes()
        self.assertNotIn(SHM1, historical)
        # Frozen M2 legacy fixture digest: no-region output must remain this
        # exact pre-SHM1 byte sequence, rather than merely decode equivalently.
        self.assertEqual(hashlib.sha256(historical).hexdigest(),
                         "2c3b6c675d87fa23f2f93f10e3ff812bb28543bb957d743b2af9f117cad85c9f")

    def test_B_shm1_round_trip_layout(self):
        config = config_with_regions([region(), region(4.0, 10.0, mass=(5, 6, 7), damping=(8, 9, 10))])
        model = config.kernel_model()
        payload = model.bytes()
        offset = payload.index(SHM1)
        marker, version, count = struct.unpack_from("<III", payload, offset)
        self.assertEqual((marker, version, count),
                         (SPANWISE_HYDRODYNAMIC_EXTENSION_MARKER,
                          SPANWISE_HYDRODYNAMIC_EXTENSION_VERSION, 2))
        values = struct.unpack_from("<8d", payload, offset + 12)
        self.assertEqual(values, model.hydrodynamic_regions[0].wire_values())
        values = struct.unpack_from("<8d", payload, offset + 12 + 64)
        self.assertEqual(values, model.hydrodynamic_regions[1].wire_values())

    def test_C_touching_and_multiple_regions_are_valid(self):
        config = config_with_regions([region(0.0, 5.0), region(5.0, 10.0)])
        self.assertEqual(len(config.kernel_model().hydrodynamic_regions), 2)

    def test_D_malformed_regions_fail_closed_in_config_and_wire(self):
        invalid = [
            [region(4.0, 4.0)], [region(-1.0, 4.0)], [region(1.0, 11.0)],
            [region(0.0, 6.0), region(5.0, 10.0)], [region(5.0, 8.0), region(1.0, 4.0)],
            [region(1.0, 4.0, mass=(-1.0, 0.0, 0.0))],
        ]
        for regions in invalid:
            with self.subTest(regions=regions):
                with self.assertRaises(CaseConfigError):
                    config_with_regions(regions)
        bad = SpanwiseHydrodynamicRegion(1.0, 2.0, (math.nan, 0.0, 0.0), (0.0, 0.0, 0.0))
        with self.assertRaises(Exception):
            replace(KernelModel(), hydrodynamic_regions=(bad,)).bytes()

    def test_E_every_region_field_changes_model_identity(self):
        base = region()
        base_config = config_with_regions([base])
        base_identity = base_config.model_identity_sha256
        direct_edits = {"s_min_m": 1.25, "s_max_m": 4.25}
        for field, replacement in direct_edits.items():
            changed = region(); changed[field] = replacement
            with self.subTest(field=field):
                self.assertNotEqual(base_identity, config_with_regions([changed]).model_identity_sha256)
        for field, baseline, delta in (
                ("added_mass_per_length_kg_m", [1.0, 2.0, 0.0], 0.5),
                ("linear_damping_per_length_Ns_m2", [3.0, 4.0, 0.0], 0.5)):
            for component, name in enumerate(("x", "y", "z")):
                changed = region(); values = list(baseline); values[component] += delta
                changed[field] = values
                with self.subTest(field=f"{field}_{name}"):
                    self.assertNotEqual(base_identity, config_with_regions([changed]).model_identity_sha256)
        self.assertNotEqual(base_identity, config_with_regions([base, region(4.0, 10.0)]).model_identity_sha256)

    def test_F_hydro_only_damping_is_representable_and_nonrayleigh(self):
        config = config_with_regions([region(damping=(0.0, 7.0, 0.0))], damping={"mode": "none"})
        model = config.kernel_model()
        self.assertEqual((model.damping_alpha, model.damping_beta), (0.0, 0.0))
        self.assertIn(SHM1, model.bytes())
        self.assertEqual(config.damping_spec()["mode"], "none")
        self.assertEqual(config.dynamic_identity_sha256((0.0,) * config.ndof),
                         config.dynamic_identity_sha256((0.0,) * config.ndof))

    def test_G_state_artifact_binds_shm1_damping_provenance(self):
        config = config_with_regions([region(damping=(0.0, 7.0, 0.0))])
        q = tuple(config.raw["initial_state"]["q"])
        artifact = config.make_state_artifact(q, (0.0,) * config.ndof, (0.0,) * config.ndof, 0.0, 0)
        self.assertEqual(artifact["damping"]["spanwise_hydrodynamic_regions"],
                         config.hydrodynamic_regions_spec())
        self.assertEqual(artifact["damping"]["identity_sha256"], config.damping_identity_sha256)
        self.assertEqual(artifact["damping"]["total_identity_sha256"],
                         config.total_damping_identity_sha256)

    def test_H_shm1_and_dmp1_keep_separate_wire_and_total_identities(self):
        config = config_with_regions([region()], damping={
            "mode": "rayleigh_coefficients", "alpha_mass_per_s": 0.1,
            "beta_stiffness_s": 0.0, "reference_state": "dynamic_initial",
            "require_free_tangent_positive_semidefinite": True,
        })
        model = config.kernel_model(); state = config.initial_state()
        request = KernelStepRequest(
            sequence=1, global_step=1, case_local_bridge_step=1,
            integer_tick=10_000_000, time_s=0.01, dt_s=0.01,
            request_id=9010, transaction_id=90010, run_id="shm1_dmp1_run", case_id="shm1_dmp1_case",
            model=model, q=state["q"], qdot=state["qdot"], qddot=state["qddot"],
            base_load=state["base_load"], slice_force=(0.0,) * (3 * model.slices),
            damping_mode="rayleigh_coefficients", damping_reference_state="dynamic_initial",
            damping_identity_sha256=config.damping_identity_sha256,
            damping_reference_state_identity_sha256=state["damping_reference_state_identity_sha256"],
            damping_model_identity_sha256=config.model_identity_sha256,
            damping_q_ref=state["damping_reference_q"],
        )
        payload = request.payload()
        self.assertIn(SHM1, payload)
        self.assertIn(struct.pack("<I", DAMPING_EXTENSION_MARKER), payload)
        self.assertNotEqual(config.damping_identity_sha256, config.total_damping_identity_sha256)

    def test_I_cpp_worker_shm1_round_trip_and_malformed_version(self):
        binary = os.environ.get("CFD_ANCF_ANCF_WORKER_BINARY")
        if not binary:
            self.skipTest("requires CFD_ANCF_ANCF_WORKER_BINARY")
        config = config_with_regions([region(0.0, 10.0, mass=(2, 3, 0), damping=(4, 5, 0))])
        model = config.kernel_model()
        state = config.initial_state()
        request = KernelStepRequest(
            sequence=1, global_step=1, case_local_bridge_step=1,
            integer_tick=10_000_000, time_s=0.01, dt_s=0.01,
            request_id=9001, transaction_id=90001, run_id="shm1_m2_run", case_id="shm1_m2_case",
            model=model, q=state["q"], qdot=state["qdot"], qddot=state["qddot"],
            base_load=state["base_load"], slice_force=(0.0,) * (3 * model.slices),
        )
        process = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(encode_control(MESSAGE_INITIALIZE)); process.stdin.flush()
        header = read_exact(process.stdout, HEADER.size)
        _, length, message_type = HEADER.unpack(header)
        self.assertEqual(message_type, MESSAGE_INITIALIZE_ACK)
        read_exact(process.stdout, length)
        process.stdin.write(encode_kernel_request(request)); process.stdin.flush()
        header = read_exact(process.stdout, HEADER.size)
        _, length, _ = HEADER.unpack(header)
        response = decode_kernel_response(header + read_exact(process.stdout, length))
        self.assertEqual(response.return_code, 0)
        process.stdin.write(encode_control(MESSAGE_SHUTDOWN)); process.stdin.flush()
        process.stdin.close(); process.wait(timeout=15)
        stderr = process.stderr.read().decode("utf-8", "replace")
        process.stdout.close(); process.stderr.close()
        self.assertEqual(process.returncode, 0, stderr)

        valid_frame = encode_kernel_request(request)
        for name, malformed in self._malformed_frames(valid_frame):
            with self.subTest(malformed=name):
                failed = subprocess.run(
                    [binary], input=encode_control(MESSAGE_INITIALIZE) + malformed,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
                self.assertNotEqual(failed.returncode, 0)

    @staticmethod
    def _malformed_frames(frame: bytes) -> list[tuple[str, bytes]]:
        marker_offset = frame.index(SHM1)
        version = bytearray(frame); struct.pack_into("<I", version, marker_offset + 4, 2)
        count = bytearray(frame); struct.pack_into("<I", count, marker_offset + 8, 10_001)
        marker = bytearray(frame); struct.pack_into("<I", marker, marker_offset, 0xDEADBEEF)
        magic, length, message_type = HEADER.unpack_from(frame)
        trailing_payload = frame[HEADER.size:] + b"bad"
        trailing = HEADER.pack(magic, length + 3, message_type) + trailing_payload
        return [
            ("bad_version", bytes(version)),
            ("impossible_count", bytes(count)),
            ("bad_marker", bytes(marker)),
            ("truncated", frame[:-8]),
            ("trailing_bytes", trailing),
        ]


if __name__ == "__main__":
    unittest.main()
