"""Runtime-only bridge for the V1 generic Ns=1 live-coupling smoke.

This script deliberately composes the committed generic SliceManifest,
PreciceStructureFleetBackend and GenericStructuralCoordinator with the existing
persistent ANCF worker protocol.  It is validation tooling, not production
coupling code and contains no benchmark-specific branch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

from coupling.arbitrary_n_live_orchestration_v1 import (
    ForceSample,
    GenericStructuralCoordinator,
    OrchestrationSlice,
    SliceManifest,
    WorkerRequest,
    assemble_generalized_force,
    build_slice_manifest,
)
from coupling.arbitrary_n_live_orchestration_v1.coordinator import _dot
from coupling.arbitrary_n_live_orchestration_v1.precice_backend import PreciceStructureFleetBackend
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    KernelModel,
    KernelStepRequest,
    MESSAGE_KERNEL_STEP_RESPONSE,
    decode_kernel_response,
    encode_kernel_request,
    validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    HEADER,
    MAGIC,
    MESSAGE_INITIALIZE,
    MESSAGE_INITIALIZE_ACK,
    MESSAGE_SHUTDOWN,
    encode_control,
)
from coupling.multi_slice_mapping.mapping import ancf_hermite_H


DT_S = 0.005
VERTEX_COUNT = 604


def _load_serialized_manifest(path: Path) -> SliceManifest:
    """Load the canonical SliceManifest JSON emitted by the generic generator.

    ``build_slice_manifest`` consumes authoring configuration (whose length
    key is ``length_m``), while ``SliceManifest.to_dict()`` emits the frozen
    runtime identity (whose corresponding field is ``reference_length_m``).
    The live validation entrypoint must preserve the latter directly instead
    of treating it as an authoring configuration.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    slices = tuple(OrchestrationSlice(**row) for row in raw["slices"])
    return SliceManifest(
        schema_version=raw["schema_version"],
        case_id=raw["case_id"],
        reference_length_m=raw["reference_length_m"],
        active_start_m=raw["active_start_m"],
        active_end_m=raw["active_end_m"],
        reconstruction_mode=raw["reconstruction_mode"],
        endpoint_policy=raw["endpoint_policy"],
        structure_participant=raw["structure_participant"],
        slices=slices,
        manifest_sha256=raw.get("manifest_sha256"),
    )


def _sha256_numbers(values: Sequence[float]) -> str:
    return hashlib.sha256(struct.pack("<" + "d" * len(values), *values)).hexdigest()


def _finite_vector(values: Sequence[float], name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or any(not math.isfinite(value) for value in result):
        raise RuntimeError(f"{name} is empty or non-finite")
    return result


def _read_exact(stream: Any, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class PersistentKernelBackend:
    """One global ANCF state, with the worker as the only numerical owner."""

    def __init__(self, manifest: SliceManifest, worker_path: str) -> None:
        if manifest.ns != 1 or manifest.reconstruction_mode != "LegacyPointLumped":
            raise RuntimeError("this bounded smoke requires one legacy slice")
        self.manifest = manifest
        self.mesh_nodes = tuple(manifest.reference_length_m * i / 4.0 for i in range(5))
        self.model = KernelModel(
            length_m=manifest.reference_length_m,
            diameter_m=0.028,
            inner_diameter_m=0.024,
            elements=4,
            slices=manifest.ns,
            top_tension_N=2000.0,
            youngs_modulus_Pa=2.07e11,
            material_density=7850.0,
            fluid_density=1025.0,
            gravity=9.81,
            beta=0.25,
            gamma=0.5,
            newton_tolerance=1.0e-8,
            damping_alpha=0.0,
            damping_beta=0.0,
            gauss_order=3,
            mass_gauss_order=5,
            max_newton=40,
            slice_positions_m=tuple(item.s_ref_m for item in manifest.slices),
        )
        q = [0.0] * self.model.ndof
        for index, s_ref in enumerate(self.mesh_nodes):
            q[6 * index + 2] = s_ref
            q[6 * index + 5] = 1.0
        self.q = tuple(q)
        self.qdot = (0.0,) * self.model.ndof
        self.qddot = (0.0,) * self.model.ndof
        self.attempted_advance_count = 0
        self.committed_advance_count = 0
        self._pending = False
        self.last_result: dict[str, Any] = {}
        self.process = subprocess.Popen(
            [worker_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("persistent ANCF worker streams are unavailable")
        self.process.stdin.write(encode_control(MESSAGE_INITIALIZE))
        self.process.stdin.flush()
        header = _read_exact(self.process.stdout, HEADER.size)
        if len(header) != HEADER.size:
            raise RuntimeError("persistent ANCF worker initialize header is missing")
        magic, length, message_type = HEADER.unpack(header)
        body = _read_exact(self.process.stdout, length)
        if magic != MAGIC or message_type != MESSAGE_INITIALIZE_ACK or len(body) != length:
            raise RuntimeError("persistent ANCF worker initialize acknowledgement is invalid")

    def snapshot(self) -> Mapping[str, Any]:
        return {
            "q": list(self.q), "qdot": list(self.qdot), "qddot": list(self.qddot),
            "attempted_advance_count": self.attempted_advance_count,
            "committed_advance_count": self.committed_advance_count,
            "pending": self._pending,
        }

    def restore(self, snapshot: Mapping[str, Any]) -> None:
        self.q = _finite_vector(snapshot["q"], "snapshot.q")
        self.qdot = _finite_vector(snapshot["qdot"], "snapshot.qdot")
        self.qddot = _finite_vector(snapshot["qddot"], "snapshot.qddot")
        self.attempted_advance_count = int(snapshot["attempted_advance_count"])
        self.committed_advance_count = int(snapshot["committed_advance_count"])
        self._pending = bool(snapshot["pending"])

    def advance(self, request: WorkerRequest) -> Mapping[str, Any]:
        if self._pending:
            raise RuntimeError("cannot make a second tentative ANCF advance")
        if request.sld1 or request.reconstruction_mode != "LegacyPointLumped":
            raise RuntimeError("smoke force request is not LegacyPointLumped")
        q_before = self.q
        self.attempted_advance_count += 1
        step = self.attempted_advance_count
        kernel_request = KernelStepRequest(
            sequence=step,
            global_step=step,
            case_local_bridge_step=step,
            integer_tick=int(math.floor(request.time_s * 1.0e9 + 0.5)),
            time_s=request.time_s,
            dt_s=DT_S,
            request_id=910000 + step,
            transaction_id=1910000 + step,
            run_id="real-single-slice-smoke-v1",
            case_id=request.case_id,
            model=self.model,
            q=self.q,
            qdot=self.qdot,
            qddot=self.qddot,
            base_load=(0.0,) * self.model.ndof,
            slice_force=request.slice_force_N,
        )
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(encode_kernel_request(kernel_request))
        self.process.stdin.flush()
        header = _read_exact(self.process.stdout, HEADER.size)
        if len(header) != HEADER.size:
            raise RuntimeError(f"persistent ANCF worker response header missing at step {step}")
        magic, length, message_type = HEADER.unpack(header)
        body = _read_exact(self.process.stdout, length)
        if magic != MAGIC or message_type != MESSAGE_KERNEL_STEP_RESPONSE or len(body) != length:
            raise RuntimeError(f"persistent ANCF worker response frame invalid at step {step}")
        response = decode_kernel_response(header + body)
        validate_kernel_response(kernel_request, response)
        self.q, self.qdot, self.qddot = response.q, response.qdot, response.qddot
        self._pending = True
        self.last_result = {
            "q_before_sha256": _sha256_numbers(q_before),
            "q_after_sha256": _sha256_numbers(self.q),
            "q_before": list(q_before),
            "q_after": list(self.q),
            "qdot_after": list(self.qdot),
            "qddot_after": list(self.qddot),
            "kernel_iterations": response.iterations,
            "kernel_residual": response.residual,
            "worker_response_payload_sha256": response.payload_hash.hex(),
            "worker_request_payload_sha256": hashlib.sha256(kernel_request.payload()).hexdigest(),
            "generalized_force": list(assemble_generalized_force(self.manifest, self.mesh_nodes, request)),
        }
        return dict(self.last_result)

    def commit(self) -> None:
        if not self._pending:
            raise RuntimeError("ANCF commit requires a tentative advance")
        self.committed_advance_count += 1
        self._pending = False

    def evaluate_position(self, s_ref_m: float) -> tuple[float, float, float]:
        H = ancf_hermite_H(s_ref_m, self.mesh_nodes, ndof=self.model.ndof)
        return _dot(H, self.q)  # type: ignore[return-value]

    def close(self) -> dict[str, Any]:
        result: dict[str, Any] = {"pid": self.process.pid, "path": str(self.process.args)}
        try:
            if self.process.poll() is None and self.process.stdin is not None:
                self.process.stdin.write(encode_control(MESSAGE_SHUTDOWN))
                self.process.stdin.flush()
                self.process.stdin.close()
            self.process.wait(timeout=20)
        except Exception as exc:
            result["shutdown_error"] = f"{type(exc).__name__}: {exc}"
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=20)
        stderr = self.process.stderr.read().decode("utf-8", errors="replace") if self.process.stderr else ""
        result.update({"return_code": self.process.returncode, "stderr": stderr, "closed": self.process.poll() is not None})
        return result


def _force_sum(value: Sequence[Sequence[float]]) -> tuple[float, float, float]:
    if len(value) != VERTEX_COUNT:
        raise RuntimeError(f"preCICE force vertex count mismatch: {len(value)} != {VERTEX_COUNT}")
    sums = [0.0, 0.0]
    for row in value:
        if len(row) != 2:
            raise RuntimeError("preCICE force dimensionality is not 2-D")
        for index in range(2):
            component = float(row[index])
            if not math.isfinite(component):
                raise RuntimeError("preCICE force contains NaN/Inf")
            sums[index] += component
    return sums[0], sums[1], 0.0


def _vertices() -> list[tuple[float, float]]:
    return [(0.5 * math.cos(2.0 * math.pi * index / VERTEX_COUNT),
             0.5 * math.sin(2.0 * math.pi * index / VERTEX_COUNT))
            for index in range(VERTEX_COUNT)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--max-windows", type=int, default=3)
    args = parser.parse_args()
    trace_path = Path(args.trace)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    output: dict[str, Any] = {
        "task": "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1",
        "generic_path": ["SliceManifest", "PreciceStructureFleetBackend", "GenericStructuralCoordinator", "persistent ANCF worker"],
        "started_unix_ns": time.time_ns(), "records": [], "error": None,
        "checkpoint_write_count": 0, "checkpoint_read_count": 0,
    }
    precice_backend: PreciceStructureFleetBackend | None = None
    worker: PersistentKernelBackend | None = None
    try:
        manifest = _load_serialized_manifest(Path(args.manifest))
        if manifest.ns != 1 or manifest.reconstruction_mode != "LegacyPointLumped":
            raise RuntimeError("manifest must be exactly Ns=1 LegacyPointLumped")
        output["manifest_sha256"] = manifest.manifest_sha256
        item = manifest.slices[0]
        precice_backend = PreciceStructureFleetBackend(
            manifest, args.config, {item.slice_id: _vertices()})
        worker = PersistentKernelBackend(manifest, args.worker)
        coordinator = GenericStructuralCoordinator(
            manifest, worker, reference_positions_by_slice={item.slice_id: (0.0, 0.0, item.s_ref_m)})
        precice_backend.initialize()
        output["precice_initialized"] = True
        initial_motion = (0.0, 0.0, 0.0)
        for window in range(1, args.max_windows + 1):
            if not precice_backend.is_coupling_ongoing():
                break
            write_checkpoint = precice_backend.requires_writing_checkpoint()
            read_checkpoint = precice_backend.requires_reading_checkpoint()
            output["checkpoint_write_count"] += int(write_checkpoint)
            output["checkpoint_read_count"] += int(read_checkpoint)
            if write_checkpoint or read_checkpoint:
                raise RuntimeError("unexpected checkpoint action in bounded parallel-explicit smoke")
            motion = coordinator.last_motion.get(item.slice_id, initial_motion)
            precice_backend.write_motion(item.slice_id, [[motion[0], motion[1]] for _ in range(VERTEX_COUNT)])
            precice_backend.advance(DT_S)
            raw_force = _force_sum(precice_backend.read_force(item.slice_id))
            sample = ForceSample.from_openfoam_integrated(
                manifest, item.slice_id, iteration=window, time_s=window * DT_S,
                force_N=raw_force, unit_span_m=item.unit_span_m)
            coordinator.submit_force(sample)
            advance_result = coordinator.advance_if_complete()
            scattered = coordinator.scatter_motion()
            coordinator.commit()
            q_finite = all(math.isfinite(value) for value in worker.q + worker.qdot + worker.qddot)
            if not q_finite:
                raise RuntimeError("ANCF state is non-finite")
            output["records"].append({
                "window": window,
                "fluid_force_timestamp_s": window * DT_S,
                "structural_motion_timestamp_s": window * DT_S,
                "force_read_count": 1,
                "complete_force_sets": 1,
                "attempted_ancf_advances": coordinator.attempted_structural_advances,
                "committed_ancf_advances": coordinator.committed_structural_advances,
                "motion_write_count": 1,
                "slice_id": item.slice_id,
                "s_ref_m": item.s_ref_m,
                "openfoam_integrated_force_N": list(raw_force),
                "unit_span_m": item.unit_span_m,
                "normalized_line_force_Npm": [value / item.unit_span_m for value in raw_force],
                "legacy_integrated_force_N": list(sample.values),
                "worker_request": coordinator.last_request.to_payload() if coordinator.last_request else None,
                "motion_xyz_m": list(scattered[item.slice_id]),
                "state_finite": q_finite,
                **advance_result,
            })
        output["accepted_windows"] = len(output["records"])
        output["final_state"] = {
            "q_sha256": _sha256_numbers(worker.q),
            "qdot_sha256": _sha256_numbers(worker.qdot),
            "qddot_sha256": _sha256_numbers(worker.qddot),
            "finite": all(math.isfinite(value) for value in worker.q + worker.qdot + worker.qddot),
        }
        if output["accepted_windows"] < 3:
            raise RuntimeError("preCICE ended before the frozen minimum of three accepted windows")
        output["status"] = "PASS"
    except Exception as exc:
        output["status"] = "FAIL"
        output["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if precice_backend is not None:
            try:
                precice_backend.finalize()
                output["precice_finalized"] = True
            except Exception as exc:
                output["precice_finalize_error"] = f"{type(exc).__name__}: {exc}"
                output["status"] = "FAIL"
        if worker is not None:
            output["worker"] = worker.close()
            if output["worker"].get("return_code") != 0:
                output["status"] = "FAIL"
        output["ended_unix_ns"] = time.time_ns()
        trace_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if output.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
