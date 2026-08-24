from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Sequence

from coupling.performance_instrumentation_matlab_worker_v1.protocol import WorkerRequest
from coupling.performance_matlab_worker_bridge_v1.transport import FileWorkerTransport


class PersistentMatlabError(RuntimeError):
    """Persistent MATLAB worker failed or returned invalid state."""


class PersistentMatlabRunner:
    """Stage95 runner interface using one user-session MATLAB worker."""

    def __init__(self, *, work_dir: Path, runtime: Path, manifest: Any, run_id: str, case_id: str,
                 source_global_step: int, source_time_s: float, source_tick: int,
                 native_resume: Path | None, dt_s: float = .00125,
                 in_memory_state: bool = False) -> None:
        self.work_dir, self.runtime, self.manifest = Path(work_dir), Path(runtime), manifest
        self.work_dir.mkdir(parents=True, exist_ok=True); self.runtime.mkdir(parents=True, exist_ok=True)
        self.run_id, self.case_id = run_id, case_id; self.source_global_step = int(source_global_step)
        self.source_time_s, self.source_tick, self.dt_s = float(source_time_s), int(source_tick), float(dt_s)
        self.native_resume = Path(native_resume) if native_resume is not None else None
        self.in_memory_state = bool(in_memory_state)
        self.committed_path = self.work_dir / "committed.mat"; self.prediction_path = self.work_dir / "prediction.mat"; self.correction_path = self.work_dir / "correction.mat"
        self.transport = FileWorkerTransport(runtime=self.runtime, run_id=run_id, case_id=case_id, timeout_s=300.0)
        self.pending: str | None = None; self.last_state: dict[str, Any] = {"q": [], "qdot": [], "qddot": []}; self.responses: list[dict[str, Any]] = []
        self.started = False; self.closed = False

    def _send(self, operation: str, step: int, time_s: float, payload: dict[str, Any]) -> dict[str, Any]:
        bridge = int(step) - self.source_global_step
        if operation not in {"initialize", "rollback"} and bridge <= 0: raise PersistentMatlabError("target step precedes source")
        request = WorkerRequest.create(operation=operation, run_id=self.run_id, case_id=self.case_id,
            global_step=int(step), case_local_bridge_step=max(0, bridge), time_s=float(time_s), integer_tick=int(round(float(time_s) * 1e9)),
            request_id=f"stage95_{operation}_{step:08d}", transaction_id=f"stage95_tx_{operation}_{step:08d}", payload=payload)
        response = self.transport.send(request); self.responses.append(response.to_dict())
        if isinstance(response.payload, dict) and isinstance(response.payload.get("state_view"), dict):
            self.last_state = response.payload["state_view"]
        return response.to_dict()

    def start(self) -> None:
        if self.started or self.closed: raise PersistentMatlabError("MATLAB runner already started or closed")
        if self.native_resume is None or not self.native_resume.is_file(): raise PersistentMatlabError("native resume checkpoint is required")
        self.transport.publish_contract(matlab_source=Path(__file__).resolve().parent.parent / "performance_matlab_worker_bridge_v1")
        srefs = [float(item.s_ref_m) for item in getattr(self.manifest, "slices", [])]
        self._send("initialize", self.source_global_step, self.source_time_s, {"operation": "initialize", "dt_s": self.dt_s,
            "start_time_s": self.source_time_s, "work_dir": str(self.work_dir), "resume_native": str(self.native_resume),
            "ancf_source": str(Path(__file__).resolve().parents[2] / "structure_ancf_matlab"), "s_ref_m": srefs,
            "in_memory_state": self.in_memory_state})
        self.started = True

    def state_view(self) -> dict[str, list[float]]:
        return {key: [float(item) for item in self.last_state.get(key, [])] for key in ("q", "qdot", "qddot")}

    def predict(self, step: int, time_s: float, previous_slice_forces: Sequence[Sequence[float]]):
        if self.pending is not None: raise PersistentMatlabError("pending MATLAB state")
        self._send("prediction", step, time_s, {"operation": "prediction", "dt_s": self.dt_s, "forces": previous_slice_forces,
            "work_dir": str(self.work_dir), "source_mat": str(self.committed_path), "target_mat": str(self.prediction_path)})
        self.pending = "prediction"; return {"step": int(step), "time_s": float(time_s)}, []

    def correct(self, step: int, time_s: float, integrated_slice_forces: Sequence[Sequence[float]]):
        if self.pending != "prediction": raise PersistentMatlabError("correction requires prediction")
        self._send("correction", step, time_s, {"operation": "correction", "dt_s": self.dt_s, "forces": integrated_slice_forces,
            "work_dir": str(self.work_dir), "source_mat": str(self.committed_path), "target_mat": str(self.correction_path)})
        self.pending = "correction"; return {"step": int(step), "time_s": float(time_s), "audit": {"worker": "persistent"}}, []

    def save_checkpoint(self, path: str | Path) -> None:
        source = self.committed_path if self.in_memory_state else (self.correction_path if self.pending == "correction" else self.committed_path)
        shutil.copy2(source, Path(path))
    def load_checkpoint(self, path: str | Path) -> None: shutil.copy2(Path(path), self.committed_path); self.pending = None
    def finalize_committed(self, token: object | None = None) -> None:
        if self.pending == "correction" and not self.in_memory_state: shutil.copy2(self.correction_path, self.committed_path)
        self.prediction_path.unlink(missing_ok=True); self.correction_path.unlink(missing_ok=True); self.pending = None
    def discard_staged(self) -> None:
        if self.in_memory_state and self.pending == "correction" and self.started:
            self._send("rollback", self.source_global_step, self.source_time_s, {"operation": "rollback"})
        self.prediction_path.unlink(missing_ok=True); self.correction_path.unlink(missing_ok=True); self.pending = None
    def shutdown(self) -> None:
        if self.closed: return
        self.discard_staged(); self.transport.stop(); self.closed = True; self.started = False

    @property
    def worker_start_count(self) -> int: return 1 if self.started or self.closed else 0

    @property
    def owned_residual(self) -> int: return 0
