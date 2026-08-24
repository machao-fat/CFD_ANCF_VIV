from __future__ import annotations
import json
from pathlib import Path
from typing import Any

class UTF8BoundaryError(ValueError):
    pass

def read_bytes(path: str | Path) -> bytes:
    data = Path(path).read_bytes()
    if data.startswith(b'\xef\xbb\xbf'):
        raise UTF8BoundaryError('UTF-8 BOM is rejected by contract')
    try:
        data.decode('utf-8', errors='strict')
    except UnicodeDecodeError as exc:
        raise UTF8BoundaryError('input is not strict UTF-8') from exc
    return data

def read_json(path: str | Path) -> Any:
    try:
        return json.loads(read_bytes(path).decode('utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UTF8BoundaryError(f'invalid UTF-8 JSON: {path}') from exc

def read_jsonl(path: str | Path) -> list[Any]:
    text = read_bytes(path).decode('utf-8')
    try:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise UTF8BoundaryError(f'invalid UTF-8 JSONL: {path}') from exc

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

def write_json(path: str | Path, value: Any) -> None:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_bytes(value) + b'\n')
