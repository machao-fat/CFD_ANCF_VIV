"""Pure JSON evidence comparison for restart identity.

This module deliberately does not invoke MATLAB, OpenFOAM, or read native
``.mat`` state.  It compares the committed JSON representation, previous CFD
forces, and the CFD field hashes already recorded in each checkpoint manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


class RestartIdentityError(ValueError):
    """Raised when a checkpoint payload is incomplete or malformed."""


@dataclass(frozen=True)
class RestartIdentityTolerances:
    """Numerical tolerances for a restarted state versus its reference."""

    structure_relative_linf: float = 1.0e-10
    previous_force_relative_linf: float = 1.0e-10
    time_absolute_s: float = 1.0e-12

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if not math.isfinite(value) or value < 0.0:
                raise RestartIdentityError(f"{name} must be finite and non-negative")


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RestartIdentityError(f"{name} must be an object")
    return value


def _finite_vector(value: object, name: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RestartIdentityError(f"{name} must be an array")
    result: list[float] = []
    for index, item in enumerate(value):
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise RestartIdentityError(f"{name}[{index}] is not numeric") from exc
        if not math.isfinite(number):
            raise RestartIdentityError(f"{name}[{index}] is non-finite")
        result.append(number)
    return result


def _force_vector(value: object, name: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RestartIdentityError(f"{name} must be a matrix")
    flattened: list[float] = []
    for row_index, row in enumerate(value):
        row_values = _finite_vector(row, f"{name}[{row_index}]")
        if len(row_values) != 3:
            raise RestartIdentityError(f"{name}[{row_index}] must contain three components")
        flattened.extend(row_values)
    return flattened


def _relative_linf(reference: Sequence[float], candidate: Sequence[float], name: str) -> dict[str, object]:
    if len(reference) != len(candidate):
        return {
            "passed": False,
            "reference_count": len(reference),
            "candidate_count": len(candidate),
            "reason": f"{name} length mismatch",
        }
    reference_linf = max((abs(value) for value in reference), default=0.0)
    max_abs_error = max((abs(actual - expected) for expected, actual in zip(reference, candidate)), default=0.0)
    return {
        "passed": True,
        "reference_count": len(reference),
        "candidate_count": len(candidate),
        "reference_linf": reference_linf,
        "max_abs_error": max_abs_error,
        "relative_linf": max_abs_error / max(reference_linf, 1.0),
    }


def _with_tolerance(result: dict[str, object], tolerance: float) -> dict[str, object]:
    if result["passed"] is False:
        return result
    relative = float(result["relative_linf"])
    result["tolerance"] = tolerance
    result["passed"] = relative <= tolerance
    return result


def _field_hashes(manifest: Mapping[str, Any]) -> dict[str, str]:
    slices = manifest.get("slices")
    if not isinstance(slices, list):
        raise RestartIdentityError("slices must be an array")
    fields: dict[str, str] = {}
    for slice_entry in slices:
        entry = _mapping(slice_entry, "slice entry")
        try:
            slice_id = int(entry["slice_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RestartIdentityError("slice entry is missing a valid slice_id") from exc
        for group in ("static_files", "time_files"):
            files = entry.get(group)
            if not isinstance(files, list):
                raise RestartIdentityError(f"slice {slice_id} {group} must be an array")
            for file_entry in files:
                file_data = _mapping(file_entry, f"slice {slice_id} {group} entry")
                relative = file_data.get("relative_path")
                digest = file_data.get("sha256")
                if not isinstance(relative, str) or not relative:
                    raise RestartIdentityError(f"slice {slice_id} {group} entry has no relative_path")
                if not isinstance(digest, str) or len(digest) != 64:
                    raise RestartIdentityError(f"slice {slice_id} {group} entry has no SHA-256")
                key = f"slice_{slice_id:04d}/{group}/{relative}"
                if key in fields:
                    raise RestartIdentityError(f"duplicate CFD manifest field {key}")
                fields[key] = digest
    return fields


def _exact(reference: object, candidate: object) -> dict[str, object]:
    return {"passed": reference == candidate, "reference": reference, "candidate": candidate}


def _lineage_value(payload: Mapping[str, Any], key: str) -> object:
    if key in payload:
        return payload[key]
    lineage = payload.get("lineage")
    if isinstance(lineage, Mapping):
        return lineage.get(key)
    return None


def compare_checkpoint_payloads(
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    tolerances: RestartIdentityTolerances | None = None,
    expected_lineage: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Compare restart state without executing either solver.

    ``expected_lineage`` maps a lineage field name to its required value.  The
    common use is ``{"restart_parent_checkpoint_sha256": reference_sha256}``.
    If a known lineage field is present on either payload, it is also compared
    directly between the two payloads.
    """
    policy = tolerances or RestartIdentityTolerances()
    policy.validate()
    reference = _mapping(reference, "reference checkpoint")
    candidate = _mapping(candidate, "candidate checkpoint")
    reference_structure = _mapping(reference.get("structure"), "reference structure")
    candidate_structure = _mapping(candidate.get("structure"), "candidate structure")

    metadata: dict[str, dict[str, object]] = {}
    for key in ("schema_version", "status", "case_id", "config_sha256", "slice_manifest_sha256", "expected_slice_ids", "dt_s"):
        metadata[key] = _exact(reference.get(key), candidate.get(key))
    try:
        reference_time = float(reference["time_s"])
        candidate_time = float(candidate["time_s"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RestartIdentityError("checkpoint time_s is missing or invalid") from exc
    if not math.isfinite(reference_time) or not math.isfinite(candidate_time):
        raise RestartIdentityError("checkpoint time_s is non-finite")
    metadata["time_s"] = {
        "passed": abs(candidate_time - reference_time) <= policy.time_absolute_s,
        "reference": reference_time,
        "candidate": candidate_time,
        "absolute_error": abs(candidate_time - reference_time),
        "tolerance": policy.time_absolute_s,
    }
    metadata["step"] = _exact(reference.get("step"), candidate.get("step"))

    structure: dict[str, dict[str, object]] = {}
    for key in ("q", "qdot", "qddot"):
        result = _relative_linf(
            _finite_vector(reference_structure.get(key), f"reference structure.{key}"),
            _finite_vector(candidate_structure.get(key), f"candidate structure.{key}"),
            f"structure.{key}",
        )
        structure[key] = _with_tolerance(result, policy.structure_relative_linf)

    forces = _with_tolerance(
        _relative_linf(
            _force_vector(reference.get("previous_slice_forces_N"), "reference previous_slice_forces_N"),
            _force_vector(candidate.get("previous_slice_forces_N"), "candidate previous_slice_forces_N"),
            "previous_slice_forces_N",
        ),
        policy.previous_force_relative_linf,
    )
    reference_hashes = _field_hashes(reference)
    candidate_hashes = _field_hashes(candidate)
    missing = sorted(set(reference_hashes).difference(candidate_hashes))
    extra = sorted(set(candidate_hashes).difference(reference_hashes))
    changed = [
        {"field": key, "reference": reference_hashes[key], "candidate": candidate_hashes[key]}
        for key in sorted(set(reference_hashes).intersection(candidate_hashes))
        if reference_hashes[key] != candidate_hashes[key]
    ]
    fields: dict[str, object] = {
        "passed": not missing and not extra and not changed,
        "reference_count": len(reference_hashes),
        "candidate_count": len(candidate_hashes),
        "missing_in_candidate": missing,
        "extra_in_candidate": extra,
        "changed": changed,
    }

    lineage: dict[str, dict[str, object]] = {}
    known_lineage = ("parent_checkpoint_sha256", "restart_parent_checkpoint_sha256", "source_checkpoint_sha256")
    for key in known_lineage:
        reference_value = _lineage_value(reference, key)
        candidate_value = _lineage_value(candidate, key)
        if reference_value is not None or candidate_value is not None:
            lineage[key] = _exact(reference_value, candidate_value)
    for key, expected in (expected_lineage or {}).items():
        lineage[str(key)] = {
            "passed": _lineage_value(candidate, str(key)) == expected,
            "expected": expected,
            "candidate": _lineage_value(candidate, str(key)),
        }

    groups: Mapping[str, object] = {
        "metadata": metadata,
        "structure": structure,
        "previous_forces": forces,
        "cfd_manifest_field_hashes": fields,
        "lineage": lineage,
    }
    passed = all(
        bool(item["passed"])
        for group in groups.values()
        for item in (group.values() if isinstance(group, Mapping) and group is not forces and group is not fields else [group])
    )
    return {
        "schema": "stage4f-c-restart-identity-comparison-1.0.0",
        "passed": passed,
        "tolerances": asdict(policy),
        "comparisons": groups,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compare_checkpoint_files(
    reference_path: str | Path,
    candidate_path: str | Path,
    *,
    tolerances: RestartIdentityTolerances | None = None,
    expected_lineage: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Load two committed checkpoint JSON files and return a comparison report."""
    reference_file = Path(reference_path)
    candidate_file = Path(candidate_path)
    try:
        reference = json.loads(reference_file.read_text(encoding="utf-8"))
        candidate = json.loads(candidate_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RestartIdentityError("unable to read checkpoint JSON") from exc
    report = compare_checkpoint_payloads(
        reference,
        candidate,
        tolerances=tolerances,
        expected_lineage=expected_lineage,
    )
    report["reference_checkpoint_path"] = str(reference_file.resolve())
    report["candidate_checkpoint_path"] = str(candidate_file.resolve())
    report["reference_checkpoint_sha256"] = _sha256_file(reference_file)
    report["candidate_checkpoint_sha256"] = _sha256_file(candidate_file)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two Stage 4F-C restart checkpoint JSON files.")
    parser.add_argument("reference")
    parser.add_argument("candidate")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-lineage-json", help="JSON object of candidate lineage values that must match")
    args = parser.parse_args(argv)
    expected_lineage = json.loads(args.expected_lineage_json) if args.expected_lineage_json else None
    if expected_lineage is not None and not isinstance(expected_lineage, Mapping):
        raise RestartIdentityError("--expected-lineage-json must decode to an object")
    report = compare_checkpoint_files(args.reference, args.candidate, expected_lineage=expected_lineage)
    serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    if args.output is None:
        print(serialized)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
