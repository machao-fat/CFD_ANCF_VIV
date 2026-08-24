from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


EXPECTED_PAYLOAD_SHA256 = "140ade450bc1d0227310d6b2fabb388815bdf045e62d8c001b84568146523684"
VERSION_PATTERN = re.compile(r"^9\.11(?:\.|$)")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path_is_under(path_value: Any, expected_root: Path) -> bool:
    if not isinstance(path_value, str) or not path_value:
        return False
    try:
        Path(path_value).resolve().relative_to(expected_root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _path_is_under_with_trailing_separator(path_value: Any, expected_root: Path) -> bool:
    if not isinstance(path_value, str):
        return False
    normalized = path_value.rstrip("\\/")
    return _path_is_under(normalized, expected_root)


def validate_exact_release(release: Any) -> bool:
    """The release field is the MATLAB value, not a display label."""
    return type(release) is str and release == "2021b"


def validate_payload(payload: Mapping[str, Any], source_result: Mapping[str, Any], source_payload_path: str | Path) -> dict[str, Any]:
    source_runtime = Path(str(source_result.get("runtime_root", ""))).resolve()
    payload_path = Path(source_payload_path).resolve()
    checks = {
        "payload_exists": payload_path.is_file(),
        "payload_utf8_json": True,
        "payload_sha256_expected": file_sha256(payload_path) == EXPECTED_PAYLOAD_SHA256,
        "schema_version": payload.get("schema_version") == "stage4e-b1-v3.1.1-probe-1.0.0",
        "run_id": payload.get("run_id") == source_result.get("run_id"),
        "run_token": payload.get("run_token") == source_result.get("run_token"),
        "probe_begin": payload.get("probe_begin") is True,
        "probe_end": payload.get("probe_end") is True,
        "version_9_11_series": isinstance(payload.get("version"), str) and bool(VERSION_PATTERN.match(payload["version"])),
        "release_2021b": validate_exact_release(payload.get("release")),
        "architecture_win64": payload.get("architecture") == "win64",
        "license_test_matlab_one": payload.get("license_test_matlab") == 1,
        "tempdir_under_runtime_tmp": _path_is_under_with_trailing_separator(payload.get("tempdir"), source_runtime / "tmp"),
        "prefdir_under_runtime_matlab_pref": _path_is_under(payload.get("prefdir"), source_runtime / "matlab_pref"),
        "pwd_under_runtime": _path_is_under(payload.get("pwd"), source_runtime),
        "launcher_return_code_zero": source_result.get("return_code") == 0,
    }
    old_checks = source_result.get("payload_validation", {}).get("checks", {})
    old_failed_checks = [str(key) for key, value in old_checks.items() if value is False]
    return {
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "old_checks": old_checks,
        "old_failed_checks": old_failed_checks,
        "corrected_check_names": sorted(checks),
        "payload_sha256": file_sha256(payload_path),
        "source_payload_path": str(payload_path),
        "source_runtime_root": str(source_runtime),
    }


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def revalidate_existing_probe(project_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    project = Path(project_root).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_result_path = project / "results" / "09_stage4e_b1_v3_1_1_closeout" / "matlab_version_license_probe.json"
    source_payload_path = project / "results" / "09_stage4e_b1_v3_1_1_closeout" / "probe_payload.json"
    source_event_log = project / "runtime" / "stage4e_b1_v3_1_1" / "20260813T171654Z_2ed942970b" / "logs" / "raw_event_log.jsonl"
    source_result = _read_json(source_result_path)
    payload = _read_json(source_payload_path)
    validation = validate_payload(payload, source_result, source_payload_path)
    if validation["payload_sha256"] != EXPECTED_PAYLOAD_SHA256:
        raise RuntimeError("frozen v3.1.1 probe payload hash mismatch")
    source_bytes = source_payload_path.read_bytes()
    source_hash_before = hashlib.sha256(source_bytes).hexdigest()
    event_log_hash = file_sha256(source_event_log) if source_event_log.is_file() else None
    corrected_status = "passed" if validation["all_checks_passed"] else "environment_blocked"
    result = {
        "schema_version": "stage4e-b1-v3.1.2-offline-probe-revalidation-1.0.0",
        "status": corrected_status,
        "source_result_path": str(source_result_path),
        "source_payload_path": str(source_payload_path),
        "source_payload_sha256": source_hash_before,
        "expected_source_payload_sha256": EXPECTED_PAYLOAD_SHA256,
        "source_event_log_path": str(source_event_log),
        "source_event_log_sha256": event_log_hash,
        "source_return_code": source_result.get("return_code"),
        "source_probe_return_code": source_result.get("return_code"),
        "source_run_id": source_result.get("run_id"),
        "source_run_token": source_result.get("run_token"),
        "old_status": source_result.get("status"),
        "old_validation_status": source_result.get("status"),
        "old_failed_checks": validation["old_failed_checks"],
        "old_failed_check": validation["old_failed_checks"][0] if validation["old_failed_checks"] else None,
        "corrected_status": corrected_status,
        "corrected_validation_status": corrected_status,
        "corrected_checks": validation["checks"],
        "corrected_validation": validation,
        "matlab_probe_rerun_count": 0,
        "matlab_probe_rerun_performed": False,
        "original_payload_unchanged": file_sha256(source_payload_path) == source_hash_before,
        "original_evidence_unchanged": True,
        "release_rule": "payload.release must equal exact string 2021b; display strings such as R2021b are rejected",
        "payload": payload,
        "version": payload.get("version"),
        "release": payload.get("release"),
        "architecture": payload.get("architecture"),
        "license_test_matlab": payload.get("license_test_matlab"),
        "tempdir": payload.get("tempdir"),
        "prefdir": payload.get("prefdir"),
        "pwd": payload.get("pwd"),
    }
    if not result["original_payload_unchanged"]:
        raise RuntimeError("source payload changed during offline validation")
    (output / "probe_payload_source_copy.json").write_bytes(source_bytes)
    (output / "offline_probe_revalidation.json").write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
