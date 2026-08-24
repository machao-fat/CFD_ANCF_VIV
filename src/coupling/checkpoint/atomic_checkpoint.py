"""Two-phase global checkpoint for the frozen 0.2.1 protocol.

The only durable commit point is the atomic replacement of a root-level
``checkpoint_<id>.json`` whose status is ``committed``.  OpenFOAM's
``motionScale`` is recorded as the case-level static file ``0/motionScale``;
it is never copied into a later time directory.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..multi_slice_mapping.mapping import (
    SCHEMA_VERSION,
    RuntimeConfig,
    SliceDefinition,
    SliceManifest,
    atomic_write_json,
    canonical_json_bytes,
    sha256_file,
    sha256_json,
)


REQUIRED_STATIC_FILES = ("motionScale",)
REQUIRED_TIME_FILES = ("U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "uniform/time")
REQUIRED_CFD_FILES = REQUIRED_STATIC_FILES + REQUIRED_TIME_FILES


class CheckpointError(RuntimeError):
    """Raised for incomplete, inconsistent or tampered checkpoint state."""


class CommittedPublishError(CheckpointError):
    """An atomic publish call failed; ``published`` disambiguates recovery."""

    def __init__(self, message: str, *, published: bool, path: Path) -> None:
        super().__init__(message)
        self.published = published
        self.path = path


@dataclass(frozen=True)
class PreparedCheckpoint:
    checkpoint_id: str
    prepared_path: Path
    manifest: Mapping[str, object]
    staged_token: object | None = None
    # Ephemeral metadata from prepare().  It is never serialized into the
    # formal manifest and is used only when an explicitly enabled caller
    # commits immediately after prepare().
    file_hash_cache: Mapping[str, Mapping[str, object]] | None = None


def _finite(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CheckpointError(f"{name} is not numeric") from exc
    if not math.isfinite(result):
        raise CheckpointError(f"{name} is NaN/Inf")
    return result


def _finite_tree(value: object, name: str) -> object:
    if isinstance(value, (list, tuple)):
        return [_finite_tree(item, f"{name}[]") for item in value]
    if isinstance(value, Mapping):
        return {str(key): _finite_tree(item, f"{name}.{key}") for key, item in value.items()}
    return _finite(value, name)


def _state_tree(value: object, name: str) -> object:
    if isinstance(value, (list, tuple)):
        return [_state_tree(item, f"{name}[]") for item in value]
    if isinstance(value, Mapping):
        return {str(key): _state_tree(item, f"{name}.{key}") for key, item in value.items()}
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    try:
        import numpy as np
        if isinstance(value, np.integer):
            return int(value)
    except ImportError:
        pass
    return _finite(value, name)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _time_close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= 1.0e-12 * max(1.0, abs(expected))


def _safe_relative(root: Path, relative: str, *, context: str) -> Path:
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    try:
        common = os.path.commonpath([str(candidate), str(root_resolved)])
    except ValueError as exc:
        raise CheckpointError(f"{context}: invalid path") from exc
    if common != str(root_resolved):
        raise CheckpointError(f"{context}: path escapes checkpoint root")
    return candidate


def _time_name(value: object) -> str:
    text = str(value)
    try:
        parsed = float(text)
    except ValueError as exc:
        raise CheckpointError(f"invalid OpenFOAM time name: {text}") from exc
    if not math.isfinite(parsed):
        raise CheckpointError("OpenFOAM time name is NaN/Inf")
    return text


def _file_entry(relative_path: str, path: Path, *, cache: dict[str, Mapping[str, object]] | None = None) -> dict[str, object]:
    if not path.is_file():
        raise CheckpointError(f"missing checkpoint file {relative_path}")
    stat = path.stat()
    digest = sha256_file(path)
    if cache is not None:
        cache[str(path.resolve())] = {
            "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "sha256": digest,
        }
    return {
        "relative_path": relative_path,
        "bytes": stat.st_size,
        "sha256": digest,
    }


class AtomicCheckpointManager:
    """Prepare all state, then atomically publish exactly one committed file."""

    def __init__(
        self,
        *,
        checkpoint_root: str | Path,
        case_root: str | Path,
        case_id: str,
        dt_s: float,
        specs: Sequence[SliceDefinition] | None = None,
        config_sha256: str | None = None,
        slice_manifest_sha256: str | None = None,
        manifest: SliceManifest | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        self.checkpoint_root = Path(checkpoint_root)
        self.case_root = Path(case_root)
        self.case_id = case_id
        self.dt_s = _finite(dt_s, "dt_s")
        if self.dt_s <= 0.0:
            raise CheckpointError("dt_s must be > 0")
        if manifest is None:
            if specs is None:
                raise CheckpointError("manifest or specs is required")
            represented = sum(float(item.slice_length_m) for item in specs)
            reference = max(represented, max(float(item.s_ref_m) for item in specs))
            manifest = SliceManifest(
                schema_version=SCHEMA_VERSION, case_id=case_id,
                reference_length_m=reference, represented_length_m=represented,
                slices=tuple(specs),
            )
        manifest.validate()
        if manifest.case_id != case_id:
            raise CheckpointError("manifest case_id mismatch")
        self.manifest = manifest
        self.runtime_config = runtime_config
        self.config_sha256 = str(config_sha256 or (runtime_config.config_sha256 if runtime_config else ""))
        self.slice_manifest_sha256 = str(slice_manifest_sha256 or manifest.slice_manifest_sha256)
        if self.slice_manifest_sha256 != manifest.slice_manifest_sha256:
            raise CheckpointError("slice_manifest_sha256 does not match formal manifest")
        if runtime_config is not None:
            runtime_config.validate_against_manifest(manifest)
            if self.config_sha256 != runtime_config.config_sha256:
                raise CheckpointError("config_sha256 does not match formal runtime config")
        if len(self.config_sha256) != 64:
            raise CheckpointError("config_sha256 must be supplied")
        self.checkpoint_root.mkdir(parents=True, exist_ok=True)
        self.case_root.mkdir(parents=True, exist_ok=True)

    @property
    def specs(self) -> tuple[SliceDefinition, ...]:
        return self.manifest.slices

    def prepare(
        self,
        *,
        step: int,
        time_s: float,
        coupling_iteration: int,
        slice_processes: Mapping[int, object],
        structure: object,
        previous_slice_forces_N: Sequence[Sequence[float]],
        previous_generalized_force: Sequence[float],
        raw_slice_forces_N: Sequence[Sequence[float]] | None = None,
        applied_slice_forces_N: Sequence[Sequence[float]] | None = None,
        stabilizer_state: Mapping[str, object] | None = None,
        run_id: str | None = None,
        time_tick: int | None = None,
        parent_checkpoint_id: str | None = None,
        raw_force_snapshot_manifests: Sequence[Mapping[str, object]] | None = None,
    ) -> PreparedCheckpoint:
        if step < 0 or coupling_iteration != 0 or time_s < 0.0:
            raise CheckpointError("invalid checkpoint step/time/iteration")
        expected_ids = {item.slice_id for item in self.specs}
        if set(slice_processes) != expected_ids:
            raise CheckpointError("checkpoint slice process set does not match manifest")
        previous_forces = self._validate_force_matrix(previous_slice_forces_N)
        generalized = list(_finite_tree(list(previous_generalized_force), "previous_generalized_force"))
        checkpoint_id = f"step{step:08d}_{uuid.uuid4().hex[:12]}"
        pending_dir = self.checkpoint_root / ".pending" / checkpoint_id
        pending_dir.mkdir(parents=True, exist_ok=False)

        slices: list[dict[str, object]] = []
        file_hash_cache: dict[str, Mapping[str, object]] | None = (
            {} if bool(getattr(self, "reuse_prepare_hashes", False)) else None
        )
        try:
            for spec in self.specs:
                descriptor = slice_processes[spec.slice_id].checkpoint_files(step, time_s)
                slices.append(self._build_slice_entry(spec, descriptor, time_s, file_hash_cache=file_hash_cache))

            exporter = getattr(structure, "export_staged_checkpoint", None)
            if exporter is None:
                raise CheckpointError("structure must expose export_staged_checkpoint")
            state = exporter()
            if not isinstance(state, Mapping):
                raise CheckpointError("export_staged_checkpoint() must return a mapping")
            for key in ("q", "qdot", "qddot"):
                if key not in state:
                    raise CheckpointError(f"ANCF checkpoint missing {key}")
            q = _finite_tree(state["q"], "q")
            qdot = _finite_tree(state["qdot"], "qdot")
            qddot = _finite_tree(state["qddot"], "qddot")
            token = state.get("checkpoint_token", getattr(structure, "staged_token", None))
            structure_relative = f"structure/{checkpoint_id}/ancf_checkpoint.json"
            structure_path = self.checkpoint_root / structure_relative
            structure_payload = {
                "solver": "ANCF", "case_id": self.case_id, "step": step,
                "time_s": time_s, "dt_s": self.dt_s, "q": q,
                "qdot": qdot, "qddot": qddot,
            }
            if token is not None:
                structure_payload["checkpoint_token"] = str(token)
            atomic_write_json(structure_path, structure_payload)
            structure_entry = {
                "solver": "ANCF",
                "checkpoint_relative_path": structure_relative,
                "checkpoint_bytes": structure_path.stat().st_size,
                "checkpoint_sha256": sha256_file(structure_path),
                "q": q, "qdot": qdot, "qddot": qddot,
            }
            if token is not None:
                structure_entry["checkpoint_token"] = str(token)
            native_exporter = getattr(structure, "export_runner_checkpoint", None)
            if native_exporter is not None:
                native_relative = f"structure/{checkpoint_id}/ancf_checkpoint.mat"
                native_path = self.checkpoint_root / native_relative
                native_exporter(native_path)
                structure_entry["runner_checkpoint_relative_path"] = native_relative
                structure_entry["runner_checkpoint_bytes"] = native_path.stat().st_size
                structure_entry["runner_checkpoint_sha256"] = sha256_file(native_path)
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "checkpoint_id": checkpoint_id,
                "case_id": self.case_id,
                "status": "prepared",
                "step": step,
                "coupling_iteration": coupling_iteration,
                "time_s": time_s,
                "dt_s": self.dt_s,
                "config_sha256": self.config_sha256,
                "slice_manifest_sha256": self.slice_manifest_sha256,
                "expected_slice_ids": [spec.slice_id for spec in self.specs],
                "slices": slices,
                "structure": structure_entry,
                "previous_slice_forces_N": previous_forces,
                "previous_generalized_force": generalized,
                "created_utc": _utc_now(),
            }
            extension_enabled = any(value is not None for value in (
                raw_slice_forces_N, applied_slice_forces_N, stabilizer_state,
                run_id, time_tick, parent_checkpoint_id,
            ))
            if extension_enabled:
                if raw_slice_forces_N is None or applied_slice_forces_N is None or stabilizer_state is None:
                    raise CheckpointError("stabilized checkpoint fields are incomplete")
                if not isinstance(run_id, str) or not run_id:
                    raise CheckpointError("stabilized checkpoint run_id is required")
                if isinstance(time_tick, bool) or not isinstance(time_tick, int) or time_tick < 0:
                    raise CheckpointError("stabilized checkpoint time_tick is invalid")
                if abs(time_s - time_tick * 1.0e-9) > 5.0e-13:
                    raise CheckpointError("stabilized checkpoint time_tick mismatch")
                manifest.update({
                    "schema_version": str(stabilizer_state.get("schema", "0.2.1+stabilizer.1")),
                    "run_id": run_id,
                    "time_tick": time_tick,
                    "canonical_time_s": format(time_tick * 1.0e-9, ".9f"),
                    "raw_slice_forces_N": self._validate_force_matrix(raw_slice_forces_N),
                    "applied_slice_forces_N": self._validate_force_matrix(applied_slice_forces_N),
                    "stabilizer_state": _state_tree(dict(stabilizer_state), "stabilizer_state"),
                    "parent_checkpoint_id": parent_checkpoint_id,
                    "transaction_state": "prepared",
                })
                if raw_force_snapshot_manifests is not None:
                    manifests = [dict(item) for item in raw_force_snapshot_manifests]
                    if len(manifests) != len(self.specs):
                        raise CheckpointError("raw force snapshot manifest count mismatch")
                    required_artifact = {"path","canonical_path","sha256","file_size","mtime_ns","run_id","case_id","global_step","slice_id","integer_tick","force_schema","artifact_creation_transaction","consumed_transaction","immutable","kind"}
                    if any(not required_artifact.issubset(item) for item in manifests):
                        raise CheckpointError("raw force snapshot manifest incomplete")
                    from ..stage4f_c_integer_serialization_repair_v1.integer import exact_int
                    try:
                        for item in manifests:
                            for field in ("file_size","mtime_ns","global_step","slice_id","integer_tick"):
                                exact_int(item[field], field)
                    except ValueError as exc:
                        raise CheckpointError(str(exc)) from exc
                    if {int(item["slice_id"]) for item in manifests} != expected_ids or any(item["kind"] != "raw" or item["immutable"] is not True or item["run_id"] != run_id or item["case_id"] != self.case_id or int(item["global_step"]) != step or int(item["integer_tick"]) != time_tick for item in manifests):
                        raise CheckpointError("raw force snapshot manifest identity mismatch")
                    from ..stage4f_c_transaction_identity_repair_v1.identity import validate_manifest_transactions
                    try:
                        validate_manifest_transactions(manifests, run_id, step, time_tick)
                    except Exception as exc:
                        raise CheckpointError(f"raw force snapshot transaction identity mismatch: {exc}") from exc
                    manifest["raw_force_snapshot_manifests"] = _state_tree(manifests, "raw_force_snapshot_manifests")
            prepared_path = pending_dir / "manifest.prepared.json"
            atomic_write_json(prepared_path, manifest)
            return PreparedCheckpoint(checkpoint_id, prepared_path, manifest, token, file_hash_cache)
        except Exception:
            # Pending evidence is retained; it can never be used for restart.
            raise

    def commit(self, prepared: PreparedCheckpoint) -> Path:
        manifest = dict(prepared.manifest)
        if manifest.get("status") != "prepared":
            raise CheckpointError("only a prepared manifest can be committed")
        self._validate_manifest(
            manifest, require_status="prepared", verify_files=True,
            file_hash_cache=(prepared.file_hash_cache if bool(getattr(self, "reuse_prepare_hashes", False)) else None),
        )
        manifest["status"] = "committed"
        if str(manifest.get("schema_version", "")).startswith("0.2.1+stabilizer."):
            manifest["transaction_state"] = "committed"
        final_path = self.checkpoint_root / f"checkpoint_{prepared.checkpoint_id}.json"
        if final_path.exists():
            raise CheckpointError(f"checkpoint already exists: {final_path}")
        try:
            atomic_write_json(final_path, manifest)
        except Exception as exc:
            published = False
            if final_path.is_file():
                try:
                    candidate = json.loads(final_path.read_text(encoding="utf-8"))
                    published = candidate.get("status") == "committed" and candidate.get("checkpoint_id") == prepared.checkpoint_id
                except Exception:
                    published = False
            raise CommittedPublishError(
                f"atomic checkpoint publish failed: {exc}",
                published=published, path=final_path,
            ) from exc
        return final_path

    def load_restart(
        self,
        manifest_path: str | Path,
        *,
        slice_processes: Mapping[int, object],
        structure: object,
    ) -> dict[str, object]:
        path = Path(manifest_path)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CheckpointError("invalid checkpoint manifest") from exc
        if not isinstance(manifest, Mapping):
            raise CheckpointError("checkpoint manifest must be an object")
        manifest_root = path.parent.resolve()
        self._validate_manifest(
            manifest, require_status="committed", verify_files=True,
            checkpoint_root=manifest_root,
        )
        if set(slice_processes) != {spec.slice_id for spec in self.specs}:
            raise CheckpointError("restart process set does not match committed slice IDs")
        for entry in sorted(manifest["slices"], key=lambda item: int(item["slice_id"])):
            sid = int(entry["slice_id"])
            slice_processes[sid].restore_checkpoint(entry)
        structure_entry = manifest["structure"]
        structure_path = _safe_relative(
            manifest_root, str(structure_entry["checkpoint_relative_path"]),
            context="structure checkpoint",
        )
        structure.load_checkpoint(structure_path)
        result = {
            "checkpoint_id": manifest["checkpoint_id"],
            "step": int(manifest["step"]),
            "time_s": float(manifest["time_s"]),
            "next_step": int(manifest["step"]) + 1,
            "next_time_s": float(manifest["time_s"]) + self.dt_s,
            "previous_slice_forces_N": manifest["previous_slice_forces_N"],
            "previous_generalized_force": manifest["previous_generalized_force"],
            "manifest_path": path,
        }
        if manifest.get("schema_version") == "0.2.1+stabilizer.1":
            result.update({
                "run_id": manifest["run_id"], "time_tick": manifest["time_tick"],
                "raw_slice_forces_N": manifest["raw_slice_forces_N"],
                "applied_slice_forces_N": manifest["applied_slice_forces_N"],
                "stabilizer_state": manifest["stabilizer_state"],
                "parent_checkpoint_id": manifest.get("parent_checkpoint_id"),
            })
        return result

    def _validate_force_matrix(self, values: Sequence[Sequence[float]]) -> list[list[float]]:
        if len(values) != len(self.specs):
            raise CheckpointError("previous_slice_forces_N has wrong slice count")
        result: list[list[float]] = []
        for index, row in enumerate(values):
            if len(row) != 3:
                raise CheckpointError(f"previous_slice_forces_N[{index}] is not 3D")
            result.append([_finite(value, f"previous_slice_forces_N[{index}][]") for value in row])
        return result

    def _build_slice_entry(
        self, spec: SliceDefinition, descriptor: object, time_s: float,
        *, file_hash_cache: dict[str, Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        if not isinstance(descriptor, Mapping):
            raise CheckpointError(f"slice {spec.slice_id}: checkpoint_files() must return a mapping")
        time_name = _time_name(descriptor.get("openfoam_time_name", ""))
        if not _time_close(float(time_name), time_s):
            raise CheckpointError(f"slice {spec.slice_id}: OpenFOAM time directory mismatch")
        case_relative = str(descriptor.get("case_relative_path", ""))
        if not case_relative or Path(case_relative).is_absolute() or ".." in Path(case_relative).parts:
            raise CheckpointError(f"slice {spec.slice_id}: invalid case_relative_path")
        static = descriptor.get("static_files")
        time_files = descriptor.get("time_files")
        if not isinstance(static, Mapping) or not isinstance(time_files, Mapping):
            raise CheckpointError(f"slice {spec.slice_id}: static_files/time_files are required")
        for required in REQUIRED_STATIC_FILES:
            if required not in static:
                raise CheckpointError(f"slice {spec.slice_id}: checkpoint missing {required}")
        for required in REQUIRED_TIME_FILES:
            if required not in time_files:
                raise CheckpointError(f"slice {spec.slice_id}: checkpoint missing {required}")
        static_entries = []
        for name in sorted(static):
            path = Path(static[name])
            static_entries.append(_file_entry(f"0/{name}", path, cache=file_hash_cache))
        time_entries = []
        for name in sorted(time_files):
            path = Path(time_files[name])
            time_entries.append(_file_entry(f"{time_name}/{name}", path, cache=file_hash_cache))
        return {
            "slice_id": spec.slice_id,
            "s_ref_m": spec.s_ref_m,
            "slice_length_m": spec.slice_length_m,
            "unit_span_m": spec.unit_span_m,
            "openfoam_time_name": time_name,
            "case_relative_path": case_relative,
            "static_files": static_entries,
            "time_files": time_entries,
        }

    def _validate_manifest(
        self, manifest: Mapping[str, object], *, require_status: str,
        verify_files: bool, checkpoint_root: Path | None = None,
        file_hash_cache: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        manifest_root = Path(checkpoint_root or self.checkpoint_root).resolve()
        required = (
            "schema_version", "checkpoint_id", "case_id", "status", "step",
            "coupling_iteration", "time_s", "dt_s", "config_sha256",
            "slice_manifest_sha256", "expected_slice_ids", "slices", "structure",
            "previous_slice_forces_N", "previous_generalized_force", "created_utc",
        )
        missing = [key for key in required if key not in manifest]
        if missing:
            raise CheckpointError(f"manifest missing fields: {', '.join(missing)}")
        schema_version = manifest["schema_version"]
        if schema_version not in (SCHEMA_VERSION, "0.2.1+stabilizer.1", "0.2.1+stabilizer.time-consistent.1") or manifest["status"] != require_status:
            raise CheckpointError("manifest schema/status is not acceptable")
        if manifest["case_id"] != self.case_id:
            raise CheckpointError("checkpoint case_id mismatch")
        if str(manifest["config_sha256"]) != self.config_sha256:
            raise CheckpointError("checkpoint config_sha256 mismatch")
        if str(manifest["slice_manifest_sha256"]) != self.slice_manifest_sha256:
            raise CheckpointError("checkpoint slice_manifest_sha256 mismatch")
        if int(manifest["coupling_iteration"]) != 0:
            raise CheckpointError("checkpoint coupling_iteration must be 0")
        step = int(manifest["step"])
        time_s = _finite(manifest["time_s"], "manifest.time_s")
        if step < 0 or time_s < 0.0 or not _time_close(_finite(manifest["dt_s"], "manifest.dt_s"), self.dt_s):
            raise CheckpointError("checkpoint step/time/dt mismatch")
        expected_ids = [spec.slice_id for spec in self.specs]
        if list(manifest["expected_slice_ids"]) != expected_ids:
            raise CheckpointError("checkpoint expected_slice_ids mismatch")
        entries = manifest["slices"]
        if not isinstance(entries, list) or len(entries) != len(self.specs):
            raise CheckpointError("checkpoint slice count mismatch")
        by_id: dict[int, Mapping[str, object]] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise CheckpointError("checkpoint slice entry is not an object")
            sid = int(entry.get("slice_id", -1))
            if sid in by_id:
                raise CheckpointError("duplicate checkpoint slice_id")
            by_id[sid] = entry
        if set(by_id) != set(expected_ids):
            raise CheckpointError("checkpoint slice_id set mismatch")
        for spec in self.specs:
            entry = by_id[spec.slice_id]
            for name, expected in (("s_ref_m", spec.s_ref_m), ("slice_length_m", spec.slice_length_m), ("unit_span_m", spec.unit_span_m)):
                if not _time_close(_finite(entry.get(name), f"checkpoint.{name}"), expected):
                    raise CheckpointError(f"slice {spec.slice_id}: {name} changed")
            time_name = _time_name(entry.get("openfoam_time_name", ""))
            if not _time_close(float(time_name), time_s):
                raise CheckpointError(f"slice {spec.slice_id}: time directory mismatch")
            static_entries = entry.get("static_files")
            time_entries = entry.get("time_files")
            if not isinstance(static_entries, list) or not isinstance(time_entries, list):
                raise CheckpointError(f"slice {spec.slice_id}: static/time file lists missing")
            all_entries = list(static_entries) + list(time_entries)
            paths: dict[str, Mapping[str, object]] = {}
            for file_entry in all_entries:
                if not isinstance(file_entry, Mapping):
                    raise CheckpointError("checkpoint file entry is not an object")
                relative = str(file_entry.get("relative_path", ""))
                if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts or relative in paths:
                    raise CheckpointError(f"slice {spec.slice_id}: invalid/duplicate file {relative}")
                paths[relative] = file_entry
            required_paths = {"0/motionScale"} | {f"{time_name}/{item}" for item in REQUIRED_TIME_FILES}
            if not required_paths.issubset(paths):
                missing_names = sorted(required_paths.difference(paths))
                raise CheckpointError(f"slice {spec.slice_id}: checkpoint missing {', '.join(missing_names)}")
            if verify_files:
                case_relative = str(entry.get("case_relative_path", ""))
                if not case_relative or Path(case_relative).is_absolute() or ".." in Path(case_relative).parts:
                    raise CheckpointError(f"slice {spec.slice_id}: invalid case_relative_path")
                for relative, file_entry in paths.items():
                    actual = self.case_root / case_relative / relative
                    if not actual.is_file():
                        raise CheckpointError(f"slice {spec.slice_id}: checkpoint file missing {relative}")
                    if int(file_entry.get("bytes", -1)) != actual.stat().st_size:
                        raise CheckpointError(f"slice {spec.slice_id}: byte count changed for {relative}")
                    expected_hash = str(file_entry.get("sha256", ""))
                    cached = file_hash_cache.get(str(actual.resolve())) if file_hash_cache is not None else None
                    if cached is not None:
                        if (int(cached.get("bytes", -1)) != int(actual.stat().st_size)
                                or int(cached.get("mtime_ns", -1)) != int(actual.stat().st_mtime_ns)
                                or str(cached.get("sha256", "")) != expected_hash):
                            raise CheckpointError(f"slice {spec.slice_id}: cached file identity changed for {relative}")
                    elif expected_hash != sha256_file(actual):
                        raise CheckpointError(f"slice {spec.slice_id}: file hash changed for {relative}")
        structure = manifest["structure"]
        if not isinstance(structure, Mapping) or structure.get("solver") != "ANCF":
            raise CheckpointError("ANCF structure entry is missing")
        for key in ("q", "qdot", "qddot"):
            if key not in structure:
                raise CheckpointError(f"ANCF checkpoint missing {key}")
            _finite_tree(structure[key], f"structure.{key}")
        if verify_files:
            structure_path = _safe_relative(
                manifest_root, str(structure.get("checkpoint_relative_path", "")),
                context="structure checkpoint",
            )
            if not structure_path.is_file():
                raise CheckpointError("ANCF checkpoint file is missing")
            if int(structure.get("checkpoint_bytes", -1)) != structure_path.stat().st_size:
                raise CheckpointError("ANCF checkpoint byte count changed")
            if str(structure.get("checkpoint_sha256", "")) != sha256_file(structure_path):
                raise CheckpointError("ANCF checkpoint hash changed")
            native_relative = structure.get("runner_checkpoint_relative_path")
            if native_relative is not None:
                native_path = _safe_relative(
                    manifest_root, str(native_relative),
                    context="native runner checkpoint",
                )
                if not native_path.is_file():
                    raise CheckpointError("native runner checkpoint is missing")
                if int(structure.get("runner_checkpoint_bytes", -1)) != native_path.stat().st_size:
                    raise CheckpointError("native runner checkpoint byte count changed")
                if str(structure.get("runner_checkpoint_sha256", "")) != sha256_file(native_path):
                    raise CheckpointError("native runner checkpoint hash changed")
            try:
                payload = json.loads(structure_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise CheckpointError("ANCF checkpoint is invalid JSON") from exc
            for key in ("q", "qdot", "qddot"):
                if payload.get(key) != structure[key]:
                    raise CheckpointError(f"ANCF checkpoint {key} disagrees with manifest")
            if int(payload.get("step", -1)) != step or not _time_close(_finite(payload.get("time_s"), "ANCF checkpoint.time_s"), time_s):
                raise CheckpointError("ANCF checkpoint step/time mismatch")
        self._validate_force_matrix(manifest["previous_slice_forces_N"])
        if not isinstance(manifest["previous_generalized_force"], list):
            raise CheckpointError("previous_generalized_force is missing")
        _finite_tree(manifest["previous_generalized_force"], "previous_generalized_force")
        if schema_version in ("0.2.1+stabilizer.1", "0.2.1+stabilizer.time-consistent.1"):
            extended = ("run_id", "time_tick", "canonical_time_s", "raw_slice_forces_N",
                        "applied_slice_forces_N", "stabilizer_state", "parent_checkpoint_id",
                        "transaction_state")
            missing_extended = [key for key in extended if key not in manifest]
            if missing_extended:
                raise CheckpointError(f"stabilized manifest missing fields: {', '.join(missing_extended)}")
            if not isinstance(manifest["run_id"], str) or not manifest["run_id"]:
                raise CheckpointError("stabilized manifest run_id is invalid")
            tick = manifest["time_tick"]
            if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
                raise CheckpointError("stabilized manifest time_tick is invalid")
            if str(manifest["canonical_time_s"]) != format(tick * 1.0e-9, ".9f") or abs(time_s - tick * 1.0e-9) > 5.0e-13:
                raise CheckpointError("stabilized manifest exact time identity mismatch")
            self._validate_force_matrix(manifest["raw_slice_forces_N"])
            self._validate_force_matrix(manifest["applied_slice_forces_N"])
            if not isinstance(manifest["stabilizer_state"], Mapping):
                raise CheckpointError("stabilizer_state must be an object")
            _state_tree(manifest["stabilizer_state"], "stabilizer_state")
            if schema_version == "0.2.1+stabilizer.time-consistent.1":
                if "raw_force_snapshot_manifests" not in manifest or len(manifest["raw_force_snapshot_manifests"]) != len(expected_ids):
                    raise CheckpointError("time-consistent raw force snapshot manifests missing")
                state=manifest["stabilizer_state"]
                from ..stage4f_c_integer_serialization_repair_v1.integer import exact_int
                required_state={"schema","contract_sha256","tau_decimal","run_id","case_id","last_time_tick","previous_applied_force_N"}
                if not required_state.issubset(state) or state["schema"]!=schema_version or state["run_id"]!=manifest["run_id"] or state["case_id"]!=manifest["case_id"] or exact_int(state["last_time_tick"],"last_time_tick")!=tick:
                    raise CheckpointError("time-consistent stabilizer state identity mismatch")
                for item in manifest["raw_force_snapshot_manifests"]:
                    size=exact_int(item["file_size"],"file_size");mtime=exact_int(item["mtime_ns"],"mtime_ns")
                    exact_int(item["global_step"],"global_step");exact_int(item["slice_id"],"slice_id");exact_int(item["integer_tick"],"integer_tick")
                    path=Path(str(item["canonical_path"])).resolve()
                    if str(path)!=str(item["path"]) or not path.is_file() or path.stat().st_size!=size or path.stat().st_mtime_ns!=mtime or sha256_file(path)!=item["sha256"]:
                        raise CheckpointError("raw force snapshot artifact changed")
            expected_transaction = "committed" if require_status == "committed" else "prepared"
            if manifest["transaction_state"] != expected_transaction:
                raise CheckpointError("stabilized transaction state mismatch")
            parent = manifest["parent_checkpoint_id"]
            if step > 0 and (not isinstance(parent, str) or not parent.startswith("checkpoint_step")):
                raise CheckpointError("stabilized checkpoint parent identity is missing or invalid")
            if isinstance(parent, str) and parent == f"checkpoint_{manifest.get('checkpoint_id', '')}":
                raise CheckpointError("stabilized checkpoint cannot parent itself")
