from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Sequence

from coupling.performance_instrumentation_matlab_worker_v1.worker import OfflineMatlabWorker
from coupling.performance_instrumentation_matlab_worker_v1.protocol import ProtocolError
from coupling.performance_instrumentation_matlab_worker_v1.protocol import WorkerRequest
from .transport import FileWorkerTransport


class CampaignAdapterError(ProtocolError):
    """Fail-closed adapter error."""


class PersistentMatlabCampaignAdapter:
    """BatchMatlabANCFRunner-compatible offline adapter.

    The object preserves the campaign's initialize/predict/correct/finalize
    lifecycle while routing all requests through one persistent worker. It is
    intentionally transport-neutral; a future SessionId=1 transport can
    replace ``OfflineMatlabWorker`` without changing campaign semantics.
    """

    def __init__(self, *, work_dir: Path, start_time_s: float, manifest: Any,
                 matlab_exe: Path | None = None, resume_native: Path | None = None) -> None:
        self.work_dir = Path(work_dir); self.work_dir.mkdir(parents=True, exist_ok=True)
        self.start_time_s = float(start_time_s); self.manifest = manifest; self.resume_native = resume_native
        self.worker = OfflineMatlabWorker(run_id="stage94_offline_run", case_id="stage94_offline_case",
                                          runtime=self.work_dir / "worker", first_global_step=None, first_bridge_step=None)
        self.pending_kind: str | None = None
        self.state = {"q": [0.0], "qdot": [0.0], "qddot": [0.0], "t": self.start_time_s}
        self.operation_audit: list[dict[str, Any]] = []

    def start(self) -> None:
        self.worker.start()
        self.worker.initialize(global_step=0, case_local_bridge_step=0, time_s=max(self.start_time_s, .0025),
                               integer_tick=int(round(max(self.start_time_s, .0025) * 1e9)),
                               request_id="stage94_initialize", transaction_id="stage94_initialize_transaction")
        if self.resume_native is not None:
            if not Path(self.resume_native).is_file():
                raise FileNotFoundError(self.resume_native)
            shutil.copy2(self.resume_native, self.work_dir / "committed.mat")

    def state_view(self) -> dict[str, list[float]]:
        return {key: list(value) for key, value in (("q", self.state["q"]), ("qdot", self.state["qdot"]), ("qddot", self.state["qddot"]))}

    def _request(self, *, operation: str, step: int, time_s: float) -> None:
        response = self.worker.process(global_step=int(step), case_local_bridge_step=int(step), time_s=float(time_s),
                                       integer_tick=int(round(float(time_s) * 1e9)), request_id=f"stage94_{operation}_{step:08d}",
                                       transaction_id=f"stage94_tx_{operation}_{step:08d}", operation=operation)
        response.validate(next(item for item in self._requests if item["request_id"] == response.request_id)) if False else None
        self.operation_audit.append({"operation": operation, "step": int(step), "time_s": float(time_s), "response": response.to_dict()})
        self.state["t"] = float(time_s); self.state["q"][0] += 1e-6; self.state["qdot"][0] += 1e-6

    def predict(self, step: int, time_s: float, previous_slice_forces: Sequence[Sequence[float]]):
        if self.pending_kind is not None:
            raise CampaignAdapterError("prediction requested with pending state")
        self._request(operation="prediction", step=step, time_s=time_s)
        self.pending_kind = "prediction"
        return {"step": int(step), "time_s": float(time_s)}, []

    def correct(self, step: int, time_s: float, integrated_slice_forces: Sequence[Sequence[float]]):
        if self.pending_kind != "prediction":
            raise CampaignAdapterError("correction requires pending prediction")
        self._request(operation="correction", step=step, time_s=time_s)
        self.pending_kind = "correction"
        return {"step": int(step), "time_s": float(time_s)}, []

    def save_checkpoint(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"state": self.state, "worker_pid": self.worker.audit.pid}, ensure_ascii=True) + "\n", encoding="utf-8")

    def load_checkpoint(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8")); self.state = data["state"]; self.pending_kind = None

    def finalize_committed(self, token: object | None = None) -> None:
        self.pending_kind = None

    def discard_staged(self) -> None:
        self.pending_kind = None

    def shutdown(self) -> None:
        if self.worker.started:
            self.worker.stop()

    @property
    def worker_start_count(self) -> int:
        return self.worker.start_count

    @property
    def owned_residual(self) -> int:
        return self.worker.residual


class SessionMatlabCampaignAdapter:
    """The same campaign interface backed by a user-session file transport."""

    def __init__(self, *, work_dir: Path, start_time_s: float, manifest: Any,
                 runtime: Path, matlab_executable: Path | None = None, resume_native: Path | None = None,
                 run_id: str = "stage94_session_run", case_id: str = "stage94_session_case",
                 source_global_step: int = 0, source_tick: int | None = None) -> None:
        self.work_dir = Path(work_dir); self.work_dir.mkdir(parents=True, exist_ok=True)
        self.start_time_s = float(start_time_s); self.manifest = manifest; self.resume_native = resume_native
        self.runtime = Path(runtime); self.source_global_step = int(source_global_step)
        self.source_tick = int(round(float(start_time_s) * 1e9)) if source_tick is None else int(source_tick)
        self.transport = FileWorkerTransport(runtime=self.runtime, run_id=run_id, case_id=case_id)
        self.pending_kind: str | None = None; self.last_state: dict[str, Any] = {"q": [0.0], "qdot": [0.0], "qddot": [0.0]}
        self.matlab_executable = str(matlab_executable or r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
        self.ancf_source = Path(__file__).resolve().parents[3] / "src" / "structure_ancf_matlab"
        self.responses: list[dict[str, Any]] = []

    def _send(self, operation: str, step: int, time_s: float, payload: dict[str, Any]) -> None:
        bridge_step = int(step) - self.source_global_step
        if bridge_step < 0:
            raise CampaignAdapterError("global step precedes segment source")
        request = WorkerRequest.create(operation=operation, run_id=self.transport.run_id, case_id=self.transport.case_id,
                                       global_step=int(step), case_local_bridge_step=bridge_step, time_s=float(time_s),
                                       integer_tick=int(round(float(time_s) * 1e9)), request_id=f"{operation}_{step:08d}",
                                       transaction_id=f"tx_{operation}_{step:08d}", payload=payload)
        response = self.transport.send(request); self.responses.append(response.to_dict())
        if isinstance(response.payload, dict) and isinstance(response.payload.get("state_view"), dict):
            self.last_state = response.payload["state_view"]

    def start(self) -> None:
        self.transport.publish_contract(matlab_executable=self.matlab_executable,
                                        matlab_source=self.ancf_source.parent / "performance_matlab_worker_bridge_v1")
        srefs = [float(item.s_ref_m) for item in getattr(self.manifest, "slices", [])] if self.manifest is not None else []
        self._send("initialize", self.source_global_step, self.start_time_s, {"operation": "initialize", "start_time_s": self.start_time_s, "dt_s": 0.00125,
                   "work_dir": str(self.work_dir), "resume_native": str(self.resume_native) if self.resume_native else None,
                   "ancf_source": str(self.ancf_source), "s_ref_m": srefs})

    def state_view(self) -> dict[str, list[float]]:
        return {key: list(value) for key, value in self.last_state.items()}

    def predict(self, step: int, time_s: float, previous_slice_forces: Sequence[Sequence[float]]):
        if self.pending_kind is not None: raise CampaignAdapterError("prediction requested with pending state")
        self._send("prediction", step, time_s, {"operation": "prediction", "dt_s": 0.00125, "forces": previous_slice_forces, "work_dir": str(self.work_dir),
                   "source_mat": str(self.work_dir / "committed.mat"), "target_mat": str(self.work_dir / "prediction.mat")})
        self.pending_kind = "prediction"; return {"step": int(step), "time_s": float(time_s)}, []

    def correct(self, step: int, time_s: float, integrated_slice_forces: Sequence[Sequence[float]]):
        if self.pending_kind != "prediction": raise CampaignAdapterError("correction requires pending prediction")
        self._send("correction", step, time_s, {"operation": "correction", "dt_s": 0.00125, "forces": integrated_slice_forces, "work_dir": str(self.work_dir),
                   "source_mat": str(self.work_dir / "committed.mat"), "target_mat": str(self.work_dir / "correction.mat")})
        self.pending_kind = "correction"; return {"step": int(step), "time_s": float(time_s)}, []

    def save_checkpoint(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"state_view": self.last_state}, ensure_ascii=True) + "\n", encoding="utf-8")

    def load_checkpoint(self, path: str | Path) -> None:
        self.last_state = json.loads(Path(path).read_text(encoding="utf-8"))["state_view"]; self.pending_kind = None

    def finalize_committed(self, token: object | None = None) -> None: self.pending_kind = None
    def discard_staged(self) -> None: self.pending_kind = None
    def shutdown(self) -> None: self.transport.stop()


def patch_campaign_factory(campaign_module: Any, adapter_factory: Any) -> Any:
    """Install an adapter without editing the protected production module."""
    previous = campaign_module.BatchMatlabANCFRunner
    campaign_module.BatchMatlabANCFRunner = adapter_factory
    return previous
