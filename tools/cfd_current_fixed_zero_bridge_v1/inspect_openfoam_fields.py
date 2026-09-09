"""Read-only, structure-aware OpenFOAM field comparison for bridge evidence.

The earlier bridge analyser searched for numbers after ``dimensions``.  That
is not a field reader: it includes list counts and dictionary metadata and it
does not distinguish internalField from value-backed boundary patches.  This
script parses the OpenFOAM field grammar needed by this case and compares
internal values, boundary value entries and points without opening a solver or
calling any demand-driven OpenFOAM getter.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "runtime" / "cfd_current_fixed_zero_bridge_v1_run_002"
OUT = ROOT / "results" / "cfd_current_fixed_zero_bridge_v1_run_002" / "field_parser_audit.json"
OLD = ROOT / "runtime" / "fixed_cylinder_precursor_initialization_v1_run_002" / "zero_motion_dynamic_restart"
PRECURSOR = ROOT / "results" / "fixed_cylinder_precursor_initialization_contract_v1_run_002" / "PRECURSOR_STATE_V1"

NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
NUMBER_RE = re.compile(NUMBER)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def matching(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unclosed {opening} at {start}")


def entry(text: str, key: str, start: int = 0) -> str | None:
    match = re.search(rf"\b{re.escape(key)}\b\s*", text[start:])
    if not match:
        return None
    begin = start + match.end()
    paren = brace = 0
    for index in range(begin, len(text)):
        char = text[index]
        if char == "(":
            paren += 1
        elif char == ")":
            paren -= 1
        elif char == "{":
            brace += 1
        elif char == "}":
            brace -= 1
        elif char == ";" and paren == 0 and brace == 0:
            return text[begin:index].strip()
    raise ValueError(f"entry {key} has no terminating semicolon")


def first_payload_parentheses(text: str, start: int = 0) -> tuple[int, int] | None:
    open_index = text.find("(", start)
    if open_index < 0:
        return None
    return open_index, matching(text, open_index, "(", ")")


def parsed_values(expression: str) -> dict[str, Any]:
    expression = expression.strip()
    lower = expression.lower()
    vector = bool(re.search(r"list\s*<\s*vector\s*>", lower)) or (
        lower.startswith("uniform") and "(" in lower
    )
    arity = 3 if vector else 1
    if lower.startswith("uniform"):
        payload = expression[len("uniform") :].strip()
        values = [float(x) for x in NUMBER_RE.findall(payload)]
        values = values[-arity:]
        return {
            "kind": "uniform",
            "declared_count": 1,
            "arity": arity,
            "values": values,
        }

    nonuniform = re.match(
        r"nonuniform\s+List\s*<\s*(scalar|vector)\s*>\s*(\d+)",
        expression,
        flags=re.I,
    )
    if not nonuniform:
        return {"kind": "unparsed", "arity": arity, "values": []}
    declared = int(nonuniform.group(2))
    payload = first_payload_parentheses(expression, nonuniform.end())
    if payload is None:
        values: list[float] = []
    else:
        body = expression[payload[0] + 1 : payload[1]]
        if arity == 3:
            values = [float(x) for x in NUMBER_RE.findall(body)]
        else:
            values = [float(x) for x in NUMBER_RE.findall(body)]
    return {
        "kind": "nonuniform",
        "declared_count": declared,
        "arity": arity,
        "values": values,
    }


def value_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    values = parsed.get("values", [])
    encoded = json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode()
    return {
        "kind": parsed.get("kind"),
        "declared_count": parsed.get("declared_count"),
        "arity": parsed.get("arity"),
        "numeric_count": len(values),
        "value_hash": hashlib.sha256(encoded).hexdigest(),
        "max_abs": max((abs(value) for value in values), default=0.0),
        "l2": math.sqrt(sum(value * value for value in values)),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def patches(text: str) -> dict[str, dict[str, Any]]:
    match = re.search(r"\bboundaryField\s*\{", text)
    if not match:
        return {}
    body_start = text.find("{", match.start())
    body_end = matching(text, body_start, "{", "}")
    body = text[body_start + 1 : body_end]
    result: dict[str, dict[str, Any]] = {}
    index = 0
    while index < len(body):
        token = re.search(r"[A-Za-z_][A-Za-z0-9_]*", body[index:])
        if not token:
            break
        name_start = index + token.start()
        name_end = index + token.end()
        cursor = name_end
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        if cursor >= len(body) or body[cursor] != "{":
            index = name_end
            continue
        end = matching(body, cursor, "{", "}")
        patch_text = body[cursor + 1 : end]
        patch_record: dict[str, Any] = {"type": entry(patch_text, "type")}
        for key in ("value", "refValue", "inletValue", "uniformValue", "gradient"):
            expression = entry(patch_text, key)
            if expression is not None:
                patch_record[key] = value_summary(parsed_values(expression))
        result[body[name_start:name_end]] = patch_record
        index = end + 1
    return result


def field(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "path": str(path)}
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = strip_comments(raw)
    internal_expression = entry(text, "internalField")
    record: dict[str, Any] = {
        "exists": True,
        "path": str(path),
        "sha256": sha256(path),
        "class": (re.search(r"\bclass\s+(\S+)\s*;", text) or [None, None])[1],
        "object": (re.search(r"\bobject\s+(\S+)\s*;", text) or [None, None])[1],
        "dimensions": entry(text, "dimensions"),
        "internalField": value_summary(parsed_values(internal_expression or "")),
        "boundaryField": patches(text),
    }
    return record


def points(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "path": str(path)}
    raw = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    parsed = parsed_values("nonuniform List<vector> " + raw.split("(", 1)[0].split()[-1] + raw[raw.find("(") :])
    return {
        "exists": True,
        "path": str(path),
        "sha256": sha256(path),
        "values": value_summary(parsed),
    }


def byte_compare(paths: list[Path]) -> dict[str, Any]:
    existing = [path for path in paths if path.is_file()]
    return {
        "paths": [str(path) for path in paths],
        "all_exist": len(existing) == len(paths),
        "byte_equal": len(existing) == len(paths) and len({path.read_bytes() for path in paths}) == 1,
        "sha256": [sha256(path) if path.is_file() else None for path in paths],
    }


def parsed_compare(paths: list[Path]) -> dict[str, Any]:
    records = [field(path) for path in paths]
    # Paths and byte hashes are evidence fields, not field-value semantics.
    # Exclude them so identical parsed fields in different directories compare
    # equal while retaining both hashes in the emitted report.
    semantic = [
        {
            key: record.get(key)
            for key in ("class", "object", "dimensions", "internalField", "boundaryField")
        }
        for record in records
    ]
    values = [json.dumps(record, sort_keys=True, separators=(",", ":")) for record in semantic]
    return {
        "paths": [str(path) for path in paths],
        "all_exist": all(record.get("exists") for record in records),
        "structured_equal": len(set(values)) == 1 if records else False,
        "records": records,
    }


def main() -> int:
    output: dict[str, Any] = {
        "schema_version": "cfd-current-fixed-zero-openfoam-field-parser-v1",
        "read_only": True,
        "solver_started": False,
        "parser_bug_explanation": {
            "old_method": "numbers after dimensions",
            "problem": "includes nonuniform list counts, vector/scalar boundary metadata and other dictionary numbers; it does not expose internalField or patch entries",
        },
        "initial_fields": {},
        "old_dynamic_vs_real_precice_zero": {},
        "selected_field_inventory": {},
    }

    for name in ("U", "p", "phi"):
        paths = [RUN / "fixed_case" / "0.1" / name, RUN / "zero_precice_case" / "0.1" / name, PRECURSOR / name]
        output["initial_fields"][name] = {
            "byte": byte_compare(paths),
            "structured": parsed_compare(paths),
        }

    for time_name in ("0.105", "0.11", "0.115", "0.12"):
        time_record: dict[str, Any] = {}
        for name in ("U", "p", "phi", "pointDisplacement", "cellDisplacement", "meshPhi"):
            paths = [OLD / time_name / name, RUN / "zero_precice_case" / time_name / name]
            time_record[name] = {
                "byte": byte_compare(paths),
                "structured": parsed_compare(paths),
            }
        output["old_dynamic_vs_real_precice_zero"][time_name] = time_record

    for time_name in ("0.1", "0.105"):
        for case_name in ("fixed_case", "zero_precice_case"):
            case = RUN / case_name
            for name in ("U", "p", "phi", "pointDisplacement", "cellDisplacement", "meshPhi", "Uf"):
                path = case / time_name / name
                output["selected_field_inventory"][f"{case_name}/{time_name}/{name}"] = field(path)
        output["selected_field_inventory"][f"zero_precice_case/{time_name}/points"] = points(
            RUN / "zero_precice_case" / time_name / "polyMesh" / "points"
        )

    # Disk-level Time/oldTime inventory only; no getter is called and no
    # solver state is opened.  In-memory oldTime layers cannot be inferred
    # from written field files and remain a separate runtime limitation.
    for case_name in ("fixed_case", "zero_precice_case"):
        case = RUN / case_name
        output.setdefault("disk_time_inventory", {})[case_name] = {
            "time_directories": sorted(
                path.name for path in case.iterdir() if path.is_dir() and re.fullmatch(r"\d+(?:\.\d+)?", path.name)
            ),
            "on_disk_oldTime_files": sorted(
                str(path.relative_to(case))
                for path in case.rglob("*")
                if path.is_file() and ("oldTime" in path.name or "oldtime" in path.name)
            ),
            "initial_uniform_time_exists": (case / "0.1" / "uniform" / "time").is_file(),
        }

    OUT.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "solver_started": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
