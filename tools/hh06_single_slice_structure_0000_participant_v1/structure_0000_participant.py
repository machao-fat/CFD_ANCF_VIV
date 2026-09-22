"""HH06 Case 1, single-slice ``Structure_0000`` preCICE wrapper.

This module is deliberately a small adapter layer.  It does not implement an
ANCF element or a new structural model: the P1 static state and explicit
section properties are loaded from the frozen HH06 artifacts, while the
existing ``PreciceStructureFleetBackend``, ``GenericStructuralCoordinator``
and persistent worker protocol remain the owners of communication,
gather/advance/scatter, and numerical integration respectively.

The default command is an offline contract audit.  A real coupling requires
the explicit ``--run`` switch and is intentionally not invoked by this file's
validation workflow.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from coupling.arbitrary_n_live_orchestration_v1 import (  # noqa: E402
    ForceSample,
    GenericStructuralCoordinator,
    OrchestrationSlice,
    SliceManifest,
    WorkerRequest,
)
from coupling.arbitrary_n_live_orchestration_v1.precice_backend import (  # noqa: E402
    PreciceStructureFleetBackend,
)
from coupling.arbitrary_n_live_orchestration_v1.coordinator import _dot  # noqa: E402
from coupling.multi_slice_mapping.mapping import ancf_hermite_H  # noqa: E402
from coupling.cpp_worker_persistent_ipc_v1.protocol import (  # noqa: E402
    HEADER,
    MAX_UINT64,
    MAGIC,
    MESSAGE_INITIALIZE,
    MESSAGE_INITIALIZE_ACK,
    MESSAGE_SHUTDOWN,
    encode_control,
)
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (  # noqa: E402
    KernelModel,
    KernelStepRequest,
    MESSAGE_KERNEL_STEP_RESPONSE,
    decode_kernel_response,
    encode_kernel_request,
    validate_kernel_response,
)


class HH06ContractError(RuntimeError):
    """A fail-closed HH06 contract or capability error."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise HH06ContractError(f"{name} is not numeric") from exc
    if not math.isfinite(result):
        raise HH06ContractError(f"{name} is NaN/Inf")
    return result


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HH06ContractError(f"missing contract document: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HH06ContractError(f"contract root is not an object: {path}")
    return value


def _resolve_path(raw: str | Path) -> Path:
    """Resolve Windows and WSL paths without changing provenance."""
    text = str(raw)
    candidate = Path(text)
    if candidate.is_file():
        return candidate
    if text.startswith("D:/") or text.startswith("D:\\"):
        wsl = Path("/mnt/d") / text[3:].replace("\\", "/")
        # P1 provenance roots are directories, while individual artifacts are
        # files.  Accept both so the same contract resolves under WSL.
        if wsl.is_file() or wsl.is_dir():
            return wsl
    if text.startswith("/mnt/") and len(text) >= 6:
        drive = text[5].upper()
        windows = Path(f"{drive}:" + text[6:].replace("/", "\\"))
        if windows.is_file():
            return windows
    return candidate


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


def _sha256_numbers(values: Sequence[float]) -> str:
    return hashlib.sha256(struct.pack("<" + "d" * len(values), *values)).hexdigest()


def _parse_q_record(path: Path, selector: str, expected_dof: int) -> tuple[float, ...]:
    """Load only the selected Q record from the verified P1 text artifact."""
    lines = path.read_text(encoding="utf-8").splitlines()
    selected = False
    for index, line in enumerate(lines):
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "CASE" and fields[1] == selector:
            selected = True
            continue
        if selected and fields and fields[0] == "CASE":
            break
        if selected and fields and fields[0] == "Q":
            try:
                count = int(fields[1])
                values = tuple(_finite(value, f"{selector}.Q[{j}]") for j, value in enumerate(fields[2:]))
            except (IndexError, ValueError) as exc:
                raise HH06ContractError(f"invalid Q record in {path} near line {index + 1}") from exc
            if count != expected_dof or len(values) != expected_dof:
                raise HH06ContractError(
                    f"{selector} Q length mismatch: declared={count}, values={len(values)}, expected={expected_dof}"
                )
            return values
    raise HH06ContractError(f"Q record {selector} not found in {path}")


@dataclass(frozen=True)
class HH06ContractBundle:
    case_dir: Path
    root: Mapping[str, Any]
    structure: Mapping[str, Any]
    mapping: Mapping[str, Any]
    interface: Mapping[str, Any]
    p1_parameters: Mapping[str, Any]
    q0: tuple[float, ...]
    q0_artifact: Path
    config_file: Path
    dt_s: float
    duration_s: float
    unit_span_m: float
    slice_length_m: float
    slice_center_m: float

    @property
    def case_id(self) -> str:
        return str(self.root["case_id"])

    @property
    def dof(self) -> int:
        return int(self.structure["geometry"]["state_dof_count"])


def load_contract_bundle(case_dir: str | Path) -> HH06ContractBundle:
    case = Path(case_dir).expanduser().resolve()
    root = _json(case / "contract.json")
    structure = _json(case / "structure_contract.json")
    mapping = _json(case / "mapping_contract.json")
    interface = _json(case / "interface_contract.json")
    source_root = _resolve_path(str(root["p1_artifact"]["root"]))
    parameter_contract = _json(source_root / str(root["p1_artifact"]["parameter_contract"]))
    q_ref = structure["static_initial_state"]["serialized_q0"]
    q0_artifact = _resolve_path(str(q_ref.get("artifact_wsl_path") or q_ref["artifact"]))
    geometry = structure["geometry"]
    dof = int(geometry["state_dof_count"])
    q0 = _parse_q_record(q0_artifact, str(q_ref.get("selector", "CASE REF_NE32")).replace("CASE ", ""), dof)
    coupling = root["coupling"]
    structural_ref = mapping["structural_reference"]
    fluid = mapping["fluid_interface"]
    config = case / "precice-config.xml"
    return HH06ContractBundle(
        case_dir=case, root=root, structure=structure, mapping=mapping, interface=interface,
        p1_parameters=parameter_contract["parameters"], q0=q0, q0_artifact=q0_artifact,
        config_file=config, dt_s=_finite(coupling["dt_s"], "coupling.dt_s"),
        duration_s=_finite(coupling["duration_s"], "coupling.duration_s"),
        unit_span_m=_finite(fluid["cfd_extrusion_span_m"], "fluid_interface.cfd_extrusion_span_m"),
        slice_length_m=_finite(structural_ref["deltaL_m"], "structural_reference.deltaL_m"),
        slice_center_m=_finite(structural_ref["slice_center_s_m"], "structural_reference.slice_center_s_m"),
    )


def build_manifest(bundle: HH06ContractBundle) -> SliceManifest:
    """Build the one-point, LegacyPointLumped orchestration manifest."""
    item = OrchestrationSlice(
        slice_id="slice_0000", ordinal=0, s_ref_m=bundle.slice_center_m,
        slice_length_m=bundle.slice_length_m, unit_span_m=bundle.unit_span_m,
        fluid_participant="Fluid_0000", structure_participant="Structure_0000",
        structure_mesh="Structure-Mesh", fluid_mesh="Fluid-Mesh",
        force_data="Force", motion_data="Displacement", openfoam_case_id=bundle.case_id,
        force_slot=0, motion_slot=0,
    )
    return SliceManifest(
        schema_version="arbitrary-n-live-coupling-v1", case_id=bundle.case_id,
        reference_length_m=float(bundle.structure["geometry"]["length_m"]),
        active_start_m=bundle.slice_center_m - 0.5 * bundle.slice_length_m,
        active_end_m=bundle.slice_center_m + 0.5 * bundle.slice_length_m,
        reconstruction_mode="LegacyPointLumped", endpoint_policy="NearestConstant",
        structure_participant="Structure_0000", slices=(item,),
    )


def _hydro_capability() -> bool:
    """Return whether this checked-out Python wire protocol emits SHM1."""
    try:
        from coupling.cpp_worker_persistent_ipc_v1 import kernel_protocol as protocol
        return hasattr(protocol, "SpanwiseHydrodynamicRegion") and hasattr(protocol.KernelModel, "__dataclass_fields__") and "hydrodynamic_regions" in protocol.KernelModel.__dataclass_fields__
    except Exception:
        return False


def audit_contract(bundle: HH06ContractBundle) -> dict[str, Any]:
    root = bundle.root
    geometry = bundle.structure["geometry"]
    pretension = bundle.structure["pretension"]
    coupling = root["coupling"]
    meshes = bundle.interface["meshes"]
    checks: dict[str, bool] = {}
    checks["status_is_dry_run"] = root.get("status") == "READY_FOR_DRY_RUN"
    checks["participants"] = (coupling.get("fluid_participant") == "Fluid_0000" and coupling.get("structure_participant") == "Structure_0000")
    checks["parallel_implicit"] = coupling.get("scheme") == "parallel-implicit"
    checks["hh06_geometry"] = (geometry.get("length_m") == 13.12 and geometry.get("diameter_m") == 0.028 and geometry.get("element_count") == 32 and geometry.get("state_dof_count") == 198)
    checks["q0_dimension_and_finite"] = len(bundle.q0) == 198 and all(math.isfinite(value) for value in bundle.q0)
    checks["one_structure_point"] = meshes["structure_coupling"].get("vertex_count") == 1
    checks["no_legacy_604_vertex"] = not bool(meshes["structure_coupling"].get("legacy_604_vertex_participant", False))
    checks["single_slice_mapping"] = (bundle.slice_center_m == 2.97 and bundle.slice_length_m == 1.98 and bundle.mapping["force_conversion"].get("double_counting_forbidden") is True)
    checks["absolute_displacement_declared"] = bundle.interface.get("displacement_type") == "absolute"
    checks["resultant_mapping_declared"] = bundle.interface.get("mapping_mode") == "single_slice_resultant_force"
    checks["tension_quantities_distinct"] = float(pretension["benchmark_top_tension_N"]) == 1175.0 and float(pretension["equilibrium_reaction_tension_N"]) == 1188.28
    try:
        ET.parse(bundle.config_file)
        checks["precice_xml_parse"] = True
    except (OSError, ET.ParseError):
        checks["precice_xml_parse"] = False
    checks["hydrodynamic_wire_extension"] = _hydro_capability()
    blocking = [name for name, passed in checks.items() if not passed]
    status = "PASS" if not blocking else "BLOCKED"
    return {
        "audit": "HH06_STRUCTURE_0000_WRAPPER_CONTRACT_AUDIT_V1",
        "status": status,
        "blocking_checks": blocking,
        "checks": checks,
        "case_dir": str(bundle.case_dir),
        "case_id": bundle.case_id,
        "participants": {"fluid": "Fluid_0000", "structure": "Structure_0000"},
        "model": {"length_m": geometry["length_m"], "diameter_m": geometry["diameter_m"], "elements": geometry["element_count"], "nodes": geometry["state_node_count"], "dof": geometry["state_dof_count"]},
        "mapping": {"mode": "single_slice_resultant_force", "structure_points": 1, "s_ref_m": bundle.slice_center_m, "deltaL_m": bundle.slice_length_m, "fluid_faces_external_only": True},
        "tension": {"benchmark_top_tension_N": pretension["benchmark_top_tension_N"], "equilibrium_reaction_tension_N": pretension["equilibrium_reaction_tension_N"]},
        "q0": {"artifact": str(bundle.q0_artifact), "sha256": _sha256(bundle.q0_artifact), "count": len(bundle.q0), "q_sha256": _sha256_numbers(bundle.q0), "velocity_zero": True},
        "wire_capability": {"SHM1_hydrodynamic_regions": _hydro_capability(), "note": "Current checked-out protocol must expose SHM1 before a wet-mass runtime is authorized."},
        "no_runtime_started": True,
    }


def _build_kernel_model(bundle: HH06ContractBundle) -> KernelModel:
    """Build the P1 explicit-section + SHM1 model; never silently fall back."""
    from coupling.cpp_worker_persistent_ipc_v1 import kernel_protocol as kp
    region_type = getattr(kp, "SpanwiseHydrodynamicRegion", None)
    if region_type is None or "hydrodynamic_regions" not in KernelModel.__dataclass_fields__:
        raise HH06ContractError("checked-out kernel protocol has no SHM1 hydrodynamic-region extension")
    params = bundle.p1_parameters
    D = float(bundle.structure["geometry"]["diameter_m"])
    area = math.pi * D * D / 4.0
    ea = float(bundle.structure["stiffness"]["EA_N"])
    hydro = bundle.structure["mass"]["added_mass_per_length_kg_m"]
    region = region_type(0.0, float(bundle.structure["geometry"]["length_m"]), tuple(float(v) for v in hydro), (0.0, 0.0, 0.0))
    kwargs: dict[str, Any] = {
        "length_m": float(bundle.structure["geometry"]["length_m"]), "diameter_m": D, "inner_diameter_m": 0.0,
        "elements": int(bundle.structure["geometry"]["element_count"]), "slices": 1,
        "top_tension_N": float(bundle.structure["pretension"]["benchmark_top_tension_N"]),
        # The explicit SPX1 line properties are authoritative.  The legacy
        # scalar density is only a required wire field; derive an equivalent
        # value from the P1 line mass and outer reference area instead of
        # importing an unrelated material-density assumption.
        "youngs_modulus_Pa": ea / area,
        "material_density": float(bundle.structure["mass"]["mass_per_length_kg_m"]) / area,
        "fluid_density": 1000.0,
        "gravity": 9.81, "beta": 0.25, "gamma": 0.5,
        "newton_tolerance": float(params.get("dynamic_newton_tolerance", {}).get("value", 2e-10)),
        "damping_alpha": float(bundle.structure["damping"]["rayleigh_alpha_1_s"]),
        "damping_beta": float(bundle.structure["damping"]["rayleigh_beta_s"]),
        "gauss_order": 3, "mass_gauss_order": 5, "max_newton": 40,
        "slice_positions_m": (bundle.slice_center_m,),
        "section_property_mode": kp.SECTION_PROPERTY_MODE_EXPLICIT,
        "explicit_EA_N": ea, "explicit_EI_Nm2": float(bundle.structure["stiffness"]["EI_Nm2"]),
        "explicit_mass_per_length_kg_m": float(bundle.structure["mass"]["mass_per_length_kg_m"]),
        "explicit_displaced_area_m2": area,
        "base_load_source": kp.BASE_LOAD_SOURCE_MODEL_STATIC,
        "hydrodynamic_regions": (region,),
    }
    return KernelModel(**kwargs)


class PersistentHH06KernelBackend:
    """Stateful Python bridge; each request still carries complete state."""

    _MAX_TRANSPORT_SEQUENCE = 0xFFFFFFFF
    _REQUEST_ID_ORIGIN = 910000
    _TRANSACTION_ID_ORIGIN = 1910000

    def __init__(self, bundle: HH06ContractBundle, manifest: SliceManifest, worker_path: str | Path) -> None:
        self.bundle = bundle
        self.manifest = manifest
        self.worker_path = str(worker_path)
        self.mesh_nodes = tuple(float(bundle.structure["geometry"]["length_m"]) * i / 32.0 for i in range(33))
        self.model = _build_kernel_model(bundle)
        self.q = tuple(bundle.q0)
        self.qdot = (0.0,) * self.model.ndof
        self.qddot = (0.0,) * self.model.ndof
        # ``attempted_advance_count`` is diagnostic only.  It is deliberately
        # not checkpointed: a retry is a new wire attempt, not a new physical
        # window, and the diagnostic count must remain monotonic as well.
        self.attempted_advance_count = 0
        self.committed_advance_count = 0
        # Transport identity belongs to the worker session, not to physical
        # solver state.  These counters therefore survive checkpoint/restore.
        self._transport_sequence_counter = 0
        self._transport_request_id_counter = self._REQUEST_ID_ORIGIN
        self._transport_transaction_id_counter = self._TRANSACTION_ID_ORIGIN
        self._pending = False
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if self.process is not None:
            raise HH06ContractError("worker already started")
        self.process = subprocess.Popen([self.worker_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if self.process.stdin is None or self.process.stdout is None:
            raise HH06ContractError("worker streams are unavailable")
        self.process.stdin.write(encode_control(MESSAGE_INITIALIZE)); self.process.stdin.flush()
        header = _read_exact(self.process.stdout, HEADER.size)
        if len(header) != HEADER.size:
            raise HH06ContractError("worker initialize acknowledgement is missing")
        magic, length, message_type = HEADER.unpack(header)
        body = _read_exact(self.process.stdout, length)
        if magic != MAGIC or message_type != MESSAGE_INITIALIZE_ACK or len(body) != length:
            raise HH06ContractError("worker initialize acknowledgement is invalid")

    def snapshot(self) -> Mapping[str, Any]:
        # A checkpoint is intentionally physical-only.  In particular, do not
        # serialize sequence/request/transaction IDs (or their generators):
        # the persistent C++ worker keeps those transport identities monotonic
        # for the whole process lifetime.
        return {
            "q": list(self.q),
            "qdot": list(self.qdot),
            "qddot": list(self.qddot),
            "committed": self.committed_advance_count,
            "pending": self._pending,
        }

    def restore(self, snapshot: Mapping[str, Any]) -> None:
        self.q = tuple(_finite(value, "snapshot.q") for value in snapshot["q"])
        self.qdot = tuple(_finite(value, "snapshot.qdot") for value in snapshot["qdot"])
        self.qddot = tuple(_finite(value, "snapshot.qddot") for value in snapshot["qddot"])
        if len(self.q) != self.model.ndof or len(self.qdot) != self.model.ndof or len(self.qddot) != self.model.ndof:
            raise HH06ContractError("checkpoint state dimension mismatch")
        pending = snapshot.get("pending", False)
        if not isinstance(pending, bool):
            raise HH06ContractError("checkpoint pending state must be boolean")
        # Older in-memory snapshots may still contain ``attempted``.  It is
        # intentionally ignored rather than copied into any transport counter.
        self.committed_advance_count = int(snapshot["committed"])
        self._pending = pending

    @staticmethod
    def _next_transport_counter(current: int, maximum: int, name: str) -> int:
        """Advance a session-monotonic wire counter, failing before wrap."""
        if current < 0 or current >= maximum:
            raise HH06ContractError(f"{name} exhausted; refusing transport-ID wraparound")
        return current + 1

    def advance(self, request: WorkerRequest) -> Mapping[str, Any]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise HH06ContractError("worker is not started")
        if self._pending:
            raise HH06ContractError("tentative worker advance is still pending")
        if request.sld1 or len(request.slice_force_N) != 3:
            raise HH06ContractError("HH06 single-slice request must be LegacyPointLumped with one resultant force")
        self.attempted_advance_count += 1
        sequence = self._next_transport_counter(
            self._transport_sequence_counter, self._MAX_TRANSPORT_SEQUENCE, "sequence"
        )
        request_id = self._next_transport_counter(
            self._transport_request_id_counter, MAX_UINT64, "request_id"
        )
        transaction_id = self._next_transport_counter(
            self._transport_transaction_id_counter, MAX_UINT64, "transaction_id"
        )
        self._transport_sequence_counter = sequence
        self._transport_request_id_counter = request_id
        self._transport_transaction_id_counter = transaction_id

        # ``global_step`` and ``case_local_bridge_step`` identify the physical
        # coupling window.  They intentionally remain unchanged on an
        # implicit retry after rollback, while the wire identity above is new.
        physical_window = self.committed_advance_count + 1
        kernel_request = KernelStepRequest(
            sequence=sequence, global_step=physical_window,
            case_local_bridge_step=physical_window, integer_tick=int(round(request.time_s * 1e9)),
            time_s=request.time_s, dt_s=self.bundle.dt_s, request_id=request_id,
            transaction_id=transaction_id, run_id="hh06-single-slice-structure-0000-v1",
            case_id=request.case_id, model=self.model, q=self.q, qdot=self.qdot, qddot=self.qddot,
            base_load=(0.0,) * self.model.ndof, slice_force=request.slice_force_N,
        )
        self.process.stdin.write(encode_kernel_request(kernel_request)); self.process.stdin.flush()
        header = _read_exact(self.process.stdout, HEADER.size)
        if len(header) != HEADER.size:
            raise HH06ContractError(f"worker response header missing at sequence {sequence}")
        magic, length, message_type = HEADER.unpack(header)
        body = _read_exact(self.process.stdout, length)
        if magic != MAGIC or message_type != MESSAGE_KERNEL_STEP_RESPONSE:
            raise HH06ContractError(f"worker response frame invalid at sequence {sequence}")
        response = decode_kernel_response(header + body); validate_kernel_response(kernel_request, response)
        self.q, self.qdot, self.qddot = response.q, response.qdot, response.qddot
        self._pending = True
        return {"iterations": response.iterations, "residual": response.residual, "q_sha256": _sha256_numbers(self.q)}

    def commit(self) -> None:
        if not self._pending:
            raise HH06ContractError("no tentative worker state to commit")
        self.committed_advance_count += 1; self._pending = False

    def evaluate_position(self, s_ref_m: float) -> tuple[float, float, float]:
        H = ancf_hermite_H(float(s_ref_m), self.mesh_nodes, ndof=self.model.ndof)
        return _dot(H, self.q)  # type: ignore[return-value]

    def close(self) -> dict[str, Any]:
        if self.process is None:
            return {"started": False}
        result: dict[str, Any] = {"started": True, "pid": self.process.pid}
        try:
            if self.process.poll() is None and self.process.stdin is not None:
                self.process.stdin.write(encode_control(MESSAGE_SHUTDOWN)); self.process.stdin.flush(); self.process.stdin.close()
            self.process.wait(timeout=20)
        except Exception as exc:
            result["shutdown_error"] = f"{type(exc).__name__}: {exc}"
            if self.process.poll() is None:
                self.process.kill(); self.process.wait(timeout=20)
        stderr = self.process.stderr.read().decode("utf-8", errors="replace") if self.process.stderr else ""
        result.update({"return_code": self.process.returncode, "stderr": stderr, "closed": self.process.poll() is not None})
        return result


def _force_total(rows: Any) -> tuple[float, float, float]:
    """Accept exactly the one mapped structural resultant, never CFD faces."""
    if hasattr(rows, "tolist"):
        rows = rows.tolist()
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise HH06ContractError("preCICE Force result is not a sequence")
    if len(rows) == 2 and all(isinstance(value, (int, float)) for value in rows):
        rows = [rows]
    if len(rows) != 1:
        raise HH06ContractError(f"Structure_0000 must receive one mapped force point, got {len(rows)}")
    row = rows[0]
    if not isinstance(row, Sequence) or len(row) not in (2, 3):
        raise HH06ContractError("mapped force point must be 2-D or 3-D")
    values = tuple(_finite(value, f"Force[{i}]") for i, value in enumerate(row))
    return (values[0], values[1], values[2] if len(values) == 3 else 0.0)


def run(case_dir: str | Path, worker_path: str | Path, max_windows: int | None = None) -> dict[str, Any]:
    """Run the live wrapper only when the caller explicitly requests it."""
    bundle = load_contract_bundle(case_dir)
    audit = audit_contract(bundle)
    if audit["status"] != "PASS":
        raise HH06ContractError("contract audit failed: " + ", ".join(audit["blocking_checks"]))
    manifest = build_manifest(bundle)
    item = manifest.slices[0]
    worker = PersistentHH06KernelBackend(bundle, manifest, worker_path)
    fleet = PreciceStructureFleetBackend(manifest, bundle.config_file, {item.slice_id: [(0.0, 0.0)]})
    coordinator = GenericStructuralCoordinator(manifest, worker, reference_positions_by_slice={item.slice_id: (0.0, 0.0, item.s_ref_m)})
    records: list[dict[str, Any]] = []
    accepted = 0
    initial_position = worker.evaluate_position(item.s_ref_m)
    initial_reference = (0.0, 0.0, item.s_ref_m)
    initial_motion = tuple(
        initial_position[index] - initial_reference[index] for index in range(3)
    )
    # The preCICE Structure mesh is one 2-D coupling point.  Only the
    # absolute section displacement (x, y) is sent; the complete 198-DOF q0
    # remains internal to the ANCF participant.
    initial_motion_by_slice = {
        item.slice_id: [[initial_motion[0], initial_motion[1]]]
    }
    committed_motion = {item.slice_id: initial_motion}
    worker.start()
    fleet.initialize(initial_motion_by_slice=initial_motion_by_slice)
    try:
        limit = int(bundle.root["coupling"]["accepted_window_limit"] if max_windows is None else max_windows)
        while fleet.is_coupling_ongoing() and accepted < limit:
            if fleet.requires_writing_checkpoint():
                coordinator.checkpoint(f"hh06-window-{accepted + 1}")
            fleet.write_motion(item.slice_id, [[committed_motion[item.slice_id][0], committed_motion[item.slice_id][1]]])
            fleet.advance(bundle.dt_s)
            raw_force = _force_total(fleet.read_force(item.slice_id))
            target_time = (accepted + 1) * bundle.dt_s
            sample = ForceSample.from_openfoam_integrated(manifest, item.slice_id, iteration=accepted + 1, time_s=target_time, force_N=raw_force, unit_span_m=bundle.unit_span_m)
            coordinator.submit_force(sample)
            result = coordinator.advance_if_complete()
            scattered = coordinator.scatter_motion()
            if fleet.requires_reading_checkpoint():
                coordinator.rollback()
                continue
            coordinator.commit(); committed_motion = scattered; accepted += 1
            records.append({"accepted_window": accepted, "time_s": target_time, "force_N": list(raw_force), "motion_m": list(scattered[item.slice_id]), **result})
    finally:
        try:
            fleet.finalize()
        finally:
            worker.close()
    return {"status": "PASS", "accepted_windows": accepted, "records": records, "manifest_sha256": manifest.manifest_sha256}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HH06 single-slice Structure_0000 adapter")
    parser.add_argument("--case", required=True, help="HH06 slice0000 case directory")
    parser.add_argument("--audit-only", action="store_true", help="validate contracts; never initialize preCICE")
    parser.add_argument("--run", action="store_true", help="explicitly enable live run (not used in offline validation)")
    parser.add_argument("--worker", help="persistent ANCF worker executable; required with --run")
    parser.add_argument("--max-windows", type=int, default=None)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args(argv)
    if args.run and not args.worker:
        parser.error("--worker is required with --run")
    try:
        bundle = load_contract_bundle(args.case)
        audit = audit_contract(bundle)
        if args.audit_output:
            args.audit_output.parent.mkdir(parents=True, exist_ok=True)
            args.audit_output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        if not args.run:
            return 0 if audit["status"] == "PASS" else 2
        result = run(args.case, args.worker, args.max_windows)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"HH06_STRUCTURE_0000_WRAPPER_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
