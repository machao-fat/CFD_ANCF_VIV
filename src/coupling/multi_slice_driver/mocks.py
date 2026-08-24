"""Deterministic 0.2.1 mock adapters and explicit transaction fault hooks."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Mapping, Sequence

from ..multi_slice_mapping.mapping import (
    SCHEMA_VERSION,
    LoadRecord,
    MotionRecord,
    RuntimeConfig,
    SliceDefinition,
    SliceManifest,
    atomic_write_csv,
    atomic_write_json,
    create_ready_marker,
    sha256_file,
)
from .contract import LOAD_FIELDS, MOTION_FIELDS, SliceExchangePaths
from .protocol import ProtocolError, publish_consumed, publish_payload, read_ready_payload, wait_consumed, wait_ready


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


class SliceProcessError(RuntimeError):
    def __init__(self, slice_id: int, message: str) -> None:
        super().__init__(f"slice_id={slice_id}: {message}")
        self.slice_id = slice_id


class MockStructureAdapter:
    """Staged state adapter: disk commit, not finalize, is the durable point."""

    def __init__(self, specs: Sequence[SliceDefinition], *, fault: str | None = None) -> None:
        self.specs = tuple(specs)
        self.fault = fault
        self.case_id = ""
        self.committed_state: dict[str, object] = {"step": -1, "time_s": 0.0, "q": [0.0], "qdot": [0.0], "qddot": [0.0]}
        self.pending_state: dict[str, object] | None = None
        self.pending_token: str | None = None
        self.commit_count = 0
        self.correct_calls = 0
        self.accepted_generalized_force: list[float] = []

    @property
    def committed_step(self) -> int:
        return int(self.committed_state["step"])

    def set_case_id(self, case_id: str) -> None:
        self.case_id = case_id

    def h_by_slice_id(self):
        return {spec.slice_id: ((0.0,), (1.0,), (0.0,)) for spec in self.specs}

    def accept_generalized_force(self, value) -> None:
        self.accepted_generalized_force = [float(item) for item in value]

    def predict_all(self, step: int, time_s: float, previous_slice_forces: Sequence[Sequence[float]]) -> list[MotionRecord]:
        if self.fault == "predict_failure":
            raise RuntimeError("mock predict failed")
        result = []
        for spec in self.specs:
            y = 0.001 * (spec.slice_id + 1) + 0.0001 * step + 0.00001 * sum(previous_slice_forces[spec.slice_id])
            if self.fault == "nan_motion" and spec.slice_id == 0:
                y = float("nan")
            result.append(MotionRecord(
                schema_version=SCHEMA_VERSION, case_id=self.case_id, step=step,
                coupling_iteration=0, time_s=time_s, slice_id=spec.slice_id,
                s_ref_m=spec.s_ref_m, slice_length_m=spec.slice_length_m,
                x_ref_m=0.0, y_ref_m=0.0, z_ref_m=spec.s_ref_m,
                ux_m=0.0, uy_m=y, uz_m=0.0,
                x_m=0.0, y_m=y, z_m=spec.s_ref_m,
                vx_mps=0.0, vy_mps=0.1, vz_mps=0.0,
                ax_mps2=0.0, ay_mps2=0.0, az_mps2=0.0,
            ))
        return result

    def correct_all(self, step: int, time_s: float, integrated_slice_forces) -> Mapping[str, object]:
        self.correct_calls += 1
        if self.fault in {"correct_failure", "staged_correction_failure"}:
            raise RuntimeError("mock staged correction failed")
        total_y = sum(float(row.force_y_N if isinstance(row, LoadRecord) else row["force_y_N"]) for row in integrated_slice_forces)
        self.pending_state = {"step": step, "time_s": time_s, "q": [total_y], "qdot": [0.1 * total_y], "qddot": [0.0]}
        self.pending_token = f"mock-token-{step}"
        return {
            "step": step, "time_s": time_s, "generalized_force": list(self.accepted_generalized_force or [total_y]),
            "checkpoint_token": self.pending_token,
            "audit": {"force_sum_y_N": total_y, "correct_calls": self.correct_calls},
        }

    def export_staged_checkpoint(self) -> Mapping[str, object]:
        if self.fault in {"staged_checkpoint_export_failure", "missing_checkpoint"}:
            raise RuntimeError("mock staged checkpoint export failed")
        state = copy.deepcopy(self.pending_state or self.committed_state)
        if self.fault == "missing_q":
            state.pop("q", None)
        elif self.fault == "missing_qdot":
            state.pop("qdot", None)
        elif self.fault == "missing_qddot":
            state.pop("qddot", None)
        state["checkpoint_token"] = self.pending_token or f"mock-token-{state['step']}"
        return state

    def finalize_committed(self, checkpoint_token=None) -> None:
        if self.fault in {"finalize_failure", "post_commit_finalize_failure"}:
            raise RuntimeError("mock finalize_committed failed")
        if self.pending_state is None:
            # Idempotent recovery after a load_checkpoint.
            return
        if checkpoint_token is not None and self.pending_token is not None and str(checkpoint_token) not in {self.pending_token, f"mock-token-{self.pending_state['step']}"}:
            raise RuntimeError("checkpoint token mismatch")
        self.committed_state = copy.deepcopy(self.pending_state)
        self.pending_state = None
        self.pending_token = None
        self.commit_count += 1

    def discard_staged(self) -> None:
        if self.pending_state is not None and self.fault == "discard_failure":
            raise RuntimeError("mock discard failed")
        self.pending_state = None
        self.pending_token = None

    def save_checkpoint(self) -> Mapping[str, object]:
        return self.export_staged_checkpoint()

    def load_checkpoint(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for key in ("step", "time_s", "q", "qdot", "qddot"):
            if key not in data:
                raise RuntimeError(f"mock structure checkpoint missing {key}")
        self.committed_state = {key: copy.deepcopy(data[key]) for key in ("step", "time_s", "q", "qdot", "qddot")}
        self.pending_state = None
        self.pending_token = None


class MockSliceProcess:
    """One deterministic CFD slice with protocol and checkpoint faults."""

    def __init__(self, spec: SliceDefinition, *, case_id: str, exchange_root: str | Path, case_root: str | Path, fault: str | None = None, consumer: str = "mock-cfd") -> None:
        self.spec = spec
        self.slice_id = spec.slice_id
        self.case_id = case_id
        self.exchange_root = Path(exchange_root)
        self.case_root = Path(case_root)
        self.fault = fault
        self.consumer = consumer
        self.manifest: SliceManifest | None = None
        self.runtime_config: RuntimeConfig | None = None
        self.last_checkpoint_time: str | None = None
        self.restored = False

    def bind_protocol(self, manifest: SliceManifest, runtime_config: RuntimeConfig) -> None:
        self.manifest = manifest
        self.runtime_config = runtime_config

    def _paths(self) -> SliceExchangePaths:
        return SliceExchangePaths(self.exchange_root, self.spec)

    def _fault(self, name: str) -> bool:
        return self.fault == name

    def publish_motion(self, record, paths: SliceExchangePaths, *, manifest: SliceManifest, runtime_config: RuntimeConfig):
        if self._fault("process_exit"):
            raise SliceProcessError(self.slice_id, "mock process exited before motion publish")
        try:
            return publish_payload(
                payload_path=paths.payload("motion", int(record.step)), ready_path=paths.ready("motion", int(record.step)),
                kind="motion", record=record, manifest=manifest, runtime_config=runtime_config,
            )
        except Exception as exc:
            raise SliceProcessError(self.slice_id, str(exc)) from exc

    def wait_motion_consumed(self, step: int, time_s: float, *, paths: SliceExchangePaths, manifest: SliceManifest, runtime_config: RuntimeConfig):
        if not self._fault("missing_motion_consumed"):
            marker = {
                "schema_version": SCHEMA_VERSION, "marker_type": "consumed", "payload_kind": "motion",
                "case_id": manifest.case_id, "slice_id": self.slice_id, "step": step,
                "coupling_iteration": 0, "time_s": time_s, "payload": paths.payload("motion", step).name,
                "payload_sha256": sha256_file(paths.payload("motion", step)), "config_sha256": runtime_config.config_sha256,
                "slice_manifest_sha256": manifest.slice_manifest_sha256, "consumer": "mock-openfoam-motion",
            }
            atomic_write_json(paths.consumed("motion", step), marker)
        try:
            return wait_consumed(paths=paths, kind="motion", step=step, time_s=time_s, manifest=manifest, runtime_config=runtime_config, timeout_s=runtime_config.timeout_s)
        except Exception as exc:
            raise SliceProcessError(self.slice_id, str(exc)) from exc

    def advance_one_step(self, step: int, time_s: float) -> None:
        if self._fault("process_exit"):
            raise SliceProcessError(self.slice_id, "mock process exited with non-zero code")
        if self._fault("timeout") or self._fault("missing_load_ready"):
            return
        assert self.manifest is not None and self.runtime_config is not None
        paths = self._paths()
        load_step = step + 1 if self._fault("early_step") or self._fault("wrong_step") else step
        load_time = time_s + 0.001 if self._fault("wrong_time") else time_s
        iteration = 1 if self._fault("wrong_iteration") else 0
        openfoam = (1.0 + self.slice_id, 2.0 + self.slice_id, 0.25 * self.slice_id)
        record = LoadRecord.from_conversion(
            case_id=self.case_id, step=load_step, time_s=load_time,
            slice_definition=self.spec, unit_span_m=self.spec.unit_span_m,
            openfoam_force_N=openfoam, cfd_time_step_s=self.runtime_config.dt_s,
            R_GL=self.manifest.R_GL,
        )
        row = record.to_dict()
        if iteration:
            row["coupling_iteration"] = iteration
        if self._fault("nan"):
            row["force_y_N"] = "nan"
        if self._fault("inf"):
            row["force_y_N"] = "inf"
        if self._fault("config_hash") or self._fault("slice_manifest_hash") or iteration or self._fault("nan") or self._fault("inf") or self._fault("wrong_step") or self._fault("wrong_time") or self._fault("early_step"):
            atomic_write_csv(paths.payload("load", step), LOAD_FIELDS, row)
            marker = {
                "schema_version": SCHEMA_VERSION, "marker_type": "ready", "payload_kind": "load",
                "case_id": self.case_id, "slice_id": self.slice_id, "step": load_step,
                "coupling_iteration": iteration, "time_s": load_time, "payload": paths.payload("load", step).name,
                "row_count": 1, "payload_sha256": sha256_file(paths.payload("load", step)),
                "config_sha256": "0" * 64 if self._fault("config_hash") else self.runtime_config.config_sha256,
                "slice_manifest_sha256": "f" * 64 if self._fault("slice_manifest_hash") else self.manifest.slice_manifest_sha256,
            }
            atomic_write_json(paths.ready("load", step), marker)
        else:
            publish_payload(
                payload_path=paths.payload("load", step), ready_path=paths.ready("load", step),
                kind="load", record=record, manifest=self.manifest, runtime_config=self.runtime_config,
            )
            if self._fault("payload_hash"):
                changed = dict(row)
                changed["force_y_N"] = float(changed["force_y_N"]) + 0.125
                changed["force_2d_y_Npm"] = float(changed["force_y_N"]) / self.spec.unit_span_m
                atomic_write_csv(paths.payload("load", step), LOAD_FIELDS, changed)
        self._write_checkpoint_files(time_s)

    def wait_load_ready(self, step: int, time_s: float, *, paths: SliceExchangePaths, manifest: SliceManifest, runtime_config: RuntimeConfig):
        try:
            return wait_ready(paths=paths, kind="load", step=step, time_s=time_s, manifest=manifest, runtime_config=runtime_config, timeout_s=runtime_config.timeout_s)
        except Exception as exc:
            raise SliceProcessError(self.slice_id, str(exc)) from exc

    def read_load(self, step: int, time_s: float):
        assert self.manifest is not None and self.runtime_config is not None
        return read_ready_payload(paths=self._paths(), kind="load", step=step, time_s=time_s, manifest=self.manifest, runtime_config=self.runtime_config, timeout_s=self.runtime_config.timeout_s)

    def publish_load_consumed(self, step: int, time_s: float, *, paths: SliceExchangePaths, manifest: SliceManifest, runtime_config: RuntimeConfig):
        try:
            return publish_consumed(paths=paths, kind="load", step=step, time_s=time_s, manifest=manifest, runtime_config=runtime_config, consumer=self.consumer)
        except Exception as exc:
            raise SliceProcessError(self.slice_id, str(exc)) from exc

    @property
    def case_relative_path(self) -> str:
        return f"slices/slice_{self.slice_id:04d}"

    def _write_checkpoint_files(self, time_s: float) -> None:
        time_name = format(time_s, ".12g")
        case_dir = self.case_root / self.case_relative_path
        (case_dir / "0").mkdir(parents=True, exist_ok=True)
        time_dir = case_dir / time_name
        time_dir.mkdir(parents=True, exist_ok=True)
        if self.fault != "checkpoint_missing_motionScale":
            atomic_write_bytes(case_dir / "0" / "motionScale", f"static motionScale slice {self.slice_id}\n".encode("utf-8"))
        for relative in REQUIRED_TIME_FILES:
            if self.fault == f"checkpoint_missing_{relative.replace('/', '_')}" or self.fault == f"checkpoint_missing_{relative}":
                continue
            atomic_write_bytes(time_dir / relative, f"{relative} slice {self.slice_id} time {time_s}\n".encode("utf-8"))
        self.last_checkpoint_time = time_name

    def checkpoint_files(self, step: int, time_s: float):
        time_name = self.last_checkpoint_time or format(time_s, ".12g")
        case_dir = self.case_root / self.case_relative_path
        time_dir = case_dir / time_name
        static = {"motionScale": case_dir / "0" / "motionScale"}
        times = {relative: time_dir / relative for relative in REQUIRED_TIME_FILES}
        return {"openfoam_time_name": time_name, "case_relative_path": self.case_relative_path, "static_files": static, "time_files": times}

    def restore_checkpoint(self, entry: Mapping[str, object]) -> None:
        if self._fault("recovery_slice_restore"):
            raise SliceProcessError(self.slice_id, "mock slice restore failed")
        self.restored = True


REQUIRED_TIME_FILES = ("U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "uniform/time")
