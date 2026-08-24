from __future__ import annotations

import json
import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any

from coupling.performance_instrumentation_matlab_worker_v1.protocol import ProtocolError, WorkerRequest, WorkerResponse, canonical_json


class FileWorkerTransport:
    """Atomic D-drive inbox/outbox transport for a user-session worker.

    This class never starts a process. The user-session runner owns the MATLAB
    process and consumes the contract/request files.
    """

    def __init__(self, *, runtime: str | Path, run_id: str, case_id: str, timeout_s: float = 180.0) -> None:
        self.runtime = Path(runtime).resolve(); self.run_id = run_id; self.case_id = case_id; self.timeout_s = float(timeout_s)
        self.inbox = self.runtime / "inbox"; self.requests = self.runtime / "requests"; self.responses = self.runtime / "responses"
        self.inbox.mkdir(parents=True, exist_ok=True); self.requests.mkdir(parents=True, exist_ok=True); self.responses.mkdir(parents=True, exist_ok=True)
        self.sequence = 0; self.started = False; self.failed = False

    def _atomic_json(self, path: Path, value: Any) -> None:
        encoded = canonical_json(value); temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
        temporary.write_bytes(encoded); os.replace(temporary, path)

    def publish_contract(self, *, expected_session_id: int = 1, expected_username: str = "Administrator",
                         matlab_executable: str = r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe",
                         matlab_batch_command: str | None = None,
                         matlab_source: str | Path | None = None) -> Path:
        if self.started or self.failed:
            raise ProtocolError("transport cannot publish a second contract")
        source = Path(matlab_source).resolve() if matlab_source is not None else Path(__file__).resolve().parent
        if matlab_batch_command is None:
            batch_command = "addpath(genpath('" + str(source).replace("'", "''").replace("\\", "/") + "')); " \
                + "stage94_matlab_worker_loop('" + str(self.runtime).replace("'", "''").replace("\\", "/") + "')"
        contract = {"contract_version": "user-session-matlab-worker.1", "run_id": self.run_id,
                    "case_id": self.case_id, "expected_session_id": expected_session_id,
                    "expected_username": expected_username, "no_cfd": True, "no_openfoam": True,
                    "no_wsl": True, "no_retry": True, "runtime": str(self.runtime),
                    "request_dir": str(self.requests), "response_dir": str(self.responses),
                    "matlab_executable": matlab_executable, "matlab_batch_command": batch_command,
                    "matlab_source": str(source) if source is not None else None,
                    "expected_release": "2021b", "expected_architecture": "win64", "worker_only": True}
        contract["contract_sha256"] = __import__("hashlib").sha256(canonical_json(contract)).hexdigest()
        path = self.inbox / f"{self.run_id}.json"; self._atomic_json(path, contract); self.started = True
        return path

    def send(self, request: WorkerRequest) -> WorkerResponse:
        if not self.started or self.failed:
            raise ProtocolError("worker transport unavailable")
        if request.run_id != self.run_id or request.case_id != self.case_id:
            raise ProtocolError("transport request identity mismatch")
        self.sequence += 1
        path = self.requests / f"{self.sequence:08d}_{request.request_id}.json"
        self._atomic_json(path, request.to_dict())
        deadline = time.monotonic() + self.timeout_s
        response_path = self.responses / path.name
        while time.monotonic() < deadline:
            if response_path.is_file():
                try:
                    raw = response_path.read_text(encoding="utf-8")
                    data = json.loads(raw)
                    response = WorkerResponse(**data)
                    response.validate(request, raw_payload_sha256=self._raw_payload_hash(raw))
                    return response
                except (OSError, ValueError, TypeError, ProtocolError) as exc:
                    self.failed = True
                    raise ProtocolError(f"worker response invalid: {exc}") from exc
            time.sleep(0.02)
        self.failed = True
        raise ProtocolError("worker response timeout")

    @staticmethod
    def _raw_payload_hash(response_text: str) -> str:
        """Hash the worker's exact serialized payload, preserving MATLAB floats.

        MATLAB R2021b and Python format finite floating-point values
        differently (notably exponent case and trailing digits).  The worker
        publishes a hash of its own JSON bytes, so re-serializing the parsed
        object in Python would reject valid responses.  This scanner extracts
        the payload value from the already-validated response object while
        respecting quoted strings and escaped characters.
        """
        marker = '"payload":'
        start = response_text.find(marker)
        if start < 0:
            raise ProtocolError("response payload field is missing")
        start += len(marker)
        depth = 0
        in_string = False
        escaped = False
        end = None
        for index in range(start, len(response_text)):
            char = response_text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None or depth != 0:
            raise ProtocolError("response payload JSON is incomplete")
        payload_bytes = (response_text[start:end] + "\n").encode("utf-8")
        return hashlib.sha256(payload_bytes).hexdigest()

    def stop(self) -> Path:
        path = self.runtime / "stop.request"; self._atomic_json(path, {"run_id": self.run_id, "request_id": uuid.uuid4().hex})
        self.started = False
        return path
