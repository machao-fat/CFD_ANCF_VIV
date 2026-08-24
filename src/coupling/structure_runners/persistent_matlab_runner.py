from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


class PersistentRunnerError(RuntimeError):
    pass


class PersistentMatlabRunner:
    """Keep one MATLAB process alive behind a sequential JSON request queue."""

    def __init__(
        self,
        *,
        branch: str,
        config: dict[str, Any],
        matlab_exe: str | Path = r"D:\Matlab\bin\matlab.exe",
        request_dir: str | Path | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.branch = branch.lower()
        if self.branch not in {"ancf", "eb"}:
            raise PersistentRunnerError(f"unsupported branch {branch}")
        self.config = config
        self.matlab_exe = str(matlab_exe)
        self.request_dir = Path(request_dir) if request_dir else Path(tempfile.mkdtemp(prefix="stage3_matlab_runner_"))
        self.response_dir = self.request_dir / "responses"
        self.request_dir.mkdir(parents=True, exist_ok=True)
        self.response_dir.mkdir(parents=True, exist_ok=True)
        self.request_path = self.request_dir / "request.json"
        self.response_path = self.response_dir / "response.json"
        self.process: subprocess.Popen[str] | None = None
        self.timeout_s = float(timeout_s)

    def start(self) -> dict[str, Any]:
        root = Path(__file__).resolve().parents[3]
        worker_root = root / "src" / "coupling" / "structure_runners"
        ancf_root = root / "src" / "structure_ancf_matlab"
        eb_root = root / "src" / "structure_eb_fem_matlab"
        command = (
            f"addpath('{worker_root}'); "
            f"matlab_structure_worker('{self.request_dir}','{ancf_root}','{eb_root}')"
        )
        log = (self.request_dir / "matlab_worker.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [self.matlab_exe, "-batch", command],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return self._call("initialize", branch=self.branch, config=self.config)

    def _call(self, action: str, **payload: Any) -> dict[str, Any]:
        if self.process is None:
            raise PersistentRunnerError("runner has not been started")
        if self.request_path.exists():
            raise PersistentRunnerError("previous request is still present")
        self.response_path.unlink(missing_ok=True)
        request = {"action": action, **payload}
        fd, temporary = tempfile.mkstemp(prefix=".request.", suffix=".tmp", dir=self.request_dir)
        os.close(fd)
        temporary_path = Path(temporary)
        try:
            temporary_path.write_text(json.dumps(request, ensure_ascii=True), encoding="utf-8")
            os.replace(temporary_path, self.request_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() <= deadline:
            if self.response_path.is_file():
                try:
                    response = json.loads(self.response_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.01)
                    continue
                self.response_path.unlink(missing_ok=True)
                if response.get("status") == "error":
                    raise PersistentRunnerError(response.get("message", "MATLAB runner error"))
                return response
            if self.process.poll() is not None:
                raise PersistentRunnerError(f"MATLAB worker exited with code {self.process.returncode}")
            time.sleep(0.01)
        raise PersistentRunnerError(f"timeout waiting for MATLAB action {action}")

    def predict(self, step: int, time_s: float, load: list[list[float]]) -> tuple[dict[str, Any], list[dict[str, str]]]:
        response = self._call("predict", step=step, time_s=time_s, load=load)
        return response, self._read_motion(response)

    def correct(self, step: int, time_s: float, load: list[list[float]]) -> tuple[dict[str, Any], list[dict[str, str]]]:
        response = self._call("correct", step=step, time_s=time_s, load=load)
        return response, self._read_motion(response)

    def get_motion(self) -> list[dict[str, str]]:
        return self._read_motion(self._call("get_motion"))

    def get_energy(self) -> dict[str, Any]:
        return self._call("get_energy").get("energy", {})

    def save_checkpoint(self, path: str | Path) -> dict[str, Any]:
        return self._call("save_checkpoint", path=str(path))

    def load_checkpoint(self, path: str | Path) -> dict[str, Any]:
        return self._call("load_checkpoint", path=str(path))

    def shutdown(self) -> None:
        if self.process is None:
            return
        try:
            self._call("shutdown")
        finally:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
            self.process = None

    def _read_motion(self, response: dict[str, Any]) -> list[dict[str, str]]:
        path = Path(response["motion_path"])
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            return list(csv.DictReader(stream))

    def __enter__(self) -> "PersistentMatlabRunner":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()
