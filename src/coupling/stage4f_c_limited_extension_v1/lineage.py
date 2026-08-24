"""Independent, append-only-style lineage reconstruction from committed files."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..multi_slice_mapping.mapping import sha256_file


class LineageError(ValueError):
    pass


def _canonical(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_ledger(rows: Iterable[Mapping[str, Any]], *, block_id: str, contract_sha256: str) -> list[dict[str, Any]]:
    ledger = []
    for row in rows:
        child = Path(str(row["checkpoint"])).resolve()
        payload = json.loads(child.read_text(encoding="utf-8"))
        if payload.get("status") != "committed" or int(payload["step"]) != int(row["physical_step"]):
            raise LineageError("summary/checkpoint commit identity mismatch")
        time_s = float(payload["time_s"])
        if not math.isfinite(time_s) or abs(time_s - float(row["target_time_s"])) > 1.0e-12:
            raise LineageError("summary/checkpoint time mismatch")
        slices = payload.get("slices")
        if not isinstance(slices, list) or len(slices) != 3:
            raise LineageError("checkpoint does not bind exactly three slices")
        field_hashes = []
        for item in slices:
            for group in ("static_files", "time_files"):
                for field in item.get(group, []):
                    field_hashes.append([int(item["slice_id"]), group, field["relative_path"], field["sha256"]])
        if len(field_hashes) != 24:
            raise LineageError("checkpoint must bind 24 CFD manifest fields")
        parent_path = Path(str(row["parent_checkpoint"])).resolve()
        parent_sha = sha256_file(parent_path)
        if parent_sha != row["parent_checkpoint_sha256"]:
            raise LineageError("parent checkpoint hash mismatch")
        record = {
            "block_id": block_id, "physical_step": int(row["physical_step"]), "time_s": time_s,
            "parent_checkpoint_absolute_path": str(parent_path), "parent_sha256": parent_sha,
            "child_checkpoint_absolute_path": str(child), "child_sha256": sha256_file(child),
            "contract_sha256": contract_sha256, "cfd_field_hashes_sha256": _canonical(field_hashes),
            "previous_slice_forces_sha256": _canonical(payload["previous_slice_forces_N"]),
            "runner_checkpoint_sha256": payload.get("structure", {}).get("runner_checkpoint_sha256"),
        }
        record["record_sha256"] = _canonical(record)
        ledger.append(record)
    validate_ledger(ledger, contract_sha256=contract_sha256)
    return ledger


def validate_ledger(rows: Iterable[Mapping[str, Any]], *, contract_sha256: str, expected_initial_parent_sha256: str | None = None) -> None:
    records = [dict(row) for row in rows]
    if not records:
        raise LineageError("lineage ledger is empty")
    if expected_initial_parent_sha256 is not None and records[0].get("parent_sha256") != expected_initial_parent_sha256:
        raise LineageError("lineage initial parent hash mismatch")
    for index, row in enumerate(records):
        supplied = row.pop("record_sha256", None)
        if supplied != _canonical(row) or row.get("contract_sha256") != contract_sha256:
            raise LineageError("lineage record hash or contract mismatch")
        if index and (records[index]["physical_step"] != records[index - 1]["physical_step"] + 1 or records[index]["parent_sha256"] != records[index - 1]["child_sha256"]):
            raise LineageError("lineage is not contiguous")
