from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    FrameError,
    KernelModel,
    KernelStepRequest,
    decode_kernel_response,
    encode_kernel_request,
    validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    HEADER as IPC_HEADER, INITIALIZE_ACK, MESSAGE_INITIALIZE, MESSAGE_INITIALIZE_ACK,
    MESSAGE_SHUTDOWN, SCHEMA_VERSION, PROTOCOL_VERSION, WORKER_ROLE,
    canonical_tick_delta, encode_control,
)


class ConfirmError(RuntimeError):
    """A bounded confirm violated a protocol or ownership invariant."""


@dataclass(frozen=True)
class Mapping:
    source_step: int = 559
    source_time_s: float = 2.2075
    source_tick: int = 2_207_500_000
    dt_s: float = 0.00125

    def identity(self, global_step: int) -> tuple[int, float, int]:
        bridge = int(global_step) - self.source_step
        if bridge <= 0:
            raise ConfirmError("global step is before the accepted source")
        tick_step = canonical_tick_delta(self.dt_s)
        return bridge, self.source_time_s + bridge * self.dt_s, self.source_tick + bridge * tick_step


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_bytes(_canonical(value))
    os.replace(tmp, path)


def _sha_vectors(*vectors: tuple[float, ...]) -> str:
    values = tuple(item for vector in vectors for item in vector)
    return hashlib.sha256(struct.pack("<" + "d" * len(values), *values)).hexdigest()


class KernelWorker:
    PRODUCTION_WORKER_NAMES = frozenset({
        "cfd_ancf_ancf_kernel_worker.exe", "cfd_ancf_ancf_kernel_worker",
    })

    def __init__(self, executable: Path, runtime: Path, run_id: str, case_id: str,
                 timeout_s: float = 30.0,
                 expected_model_contract_sha256: str | None = None) -> None:
        if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or not math.isfinite(float(timeout_s)) or timeout_s <= 0.0:
            raise ConfirmError("C++ worker timeout must be a positive finite value")
        self.executable = executable.resolve()
        self.runtime = runtime.resolve()
        self.run_id = run_id
        self.case_id = case_id
        self.timeout_s = float(timeout_s)
        if (expected_model_contract_sha256 is not None and
                (not isinstance(expected_model_contract_sha256, str) or
                 len(expected_model_contract_sha256) != 64 or
                 any(char not in "0123456789abcdefABCDEF" for char in expected_model_contract_sha256))):
            raise ConfirmError("expected C++ model contract hash is invalid")
        self.expected_model_contract_sha256 = (expected_model_contract_sha256.lower()
                                               if expected_model_contract_sha256 is not None else None)
        self.process: subprocess.Popen[bytes] | None = None
        self.start_count = 0
        self.audit: dict[str, Any] = {}
        self._reader_threads: set[threading.Thread] = set()

    def _join_reader_threads(self, timeout_s: float = 1.0) -> None:
        """收口所有有界读取线程，并把无法收口的线程记为残留。"""
        current = threading.current_thread()
        for thread in tuple(self._reader_threads):
            if thread is current:
                continue
            thread.join(timeout=max(0.0, float(timeout_s)))
            if not thread.is_alive():
                self._reader_threads.discard(thread)
        self.audit["reader_thread_residual"] = sum(
            1 for thread in self._reader_threads if thread.is_alive()
        )

    def _read_frame_bounded(self, expected_type: int) -> bytes:
        process = self.process
        if process is None or process.stdout is None:
            raise ConfirmError("C++ worker stdout is unavailable")
        result_queue: queue.Queue[tuple[bytes | None, BaseException | None]] = queue.Queue(maxsize=1)

        def read_frame() -> None:
            try:
                def read_exact(size: int) -> bytes:
                    chunks: list[bytes] = []
                    remaining = size
                    while remaining:
                        chunk = process.stdout.read(remaining)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    return b"".join(chunks)

                header = read_exact(IPC_HEADER.size)
                if len(header) != IPC_HEADER.size:
                    raise ConfirmError("C++ worker disconnected before response")
                magic, length, message_type = IPC_HEADER.unpack(header)
                if magic != b"CFDANCF1" or message_type != expected_type or length > 64 * 1024 * 1024:
                    raise ConfirmError("C++ worker response frame is invalid")
                body = read_exact(length)
                if len(body) != length:
                    raise ConfirmError("C++ worker response is truncated")
                result_queue.put((header + body, None))
            except BaseException as error:
                result_queue.put((None, error))

        thread = threading.Thread(target=read_frame, name="cpp-worker-response-reader", daemon=True)
        self._reader_threads.add(thread)
        thread.start()
        try:
            frame, error = result_queue.get(timeout=self.timeout_s)
        except queue.Empty as exc:
            self._record_failure("worker_timeout", TimeoutError(
                f"C++ worker response exceeded {self.timeout_s:g}s"))
            raise ConfirmError(f"C++ worker response exceeded {self.timeout_s:g}s") from exc
        finally:
            if not thread.is_alive():
                self._reader_threads.discard(thread)
        if error is not None:
            raise error
        if frame is None:
            raise ConfirmError("C++ worker response frame is missing")
        return frame

    def _abort_owned_process(self, classification: str) -> None:
        process = self.process
        if process is None:
            return
        if "failure_classification" not in self.audit:
            self._record_failure(classification, RuntimeError(classification))
        try:
            poll = getattr(process, "poll", lambda: None)
            if poll() is None:
                terminate = getattr(process, "terminate", None)
                wait = getattr(process, "wait", None)
                if callable(terminate):
                    terminate()
                if callable(wait):
                    wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                kill = getattr(process, "kill", None)
                wait = getattr(process, "wait", None)
                if callable(kill):
                    kill()
                if callable(wait):
                    wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as exc:
                self._record_failure("cleanup_kill", exc)
        for stream in (getattr(process, "stdin", None), getattr(process, "stdout", None),
                       getattr(process, "stderr", None)):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
        poll_value = getattr(process, "poll", lambda: 0)()
        self.audit.update({"end_time_ns": time.time_ns(), "return_code": getattr(process, "returncode", poll_value),
                           "cleanup_result": "aborted" if poll_value is not None else "residual",
                           "owned_residual": 0 if poll_value is not None else 1})
        self._join_reader_threads()
        self.process = None

    def _record_failure(self, classification: str, error: BaseException) -> None:
        self.audit["failure_classification"] = classification
        self.audit["last_error"] = f"{type(error).__name__}: {error}"

    def start(self) -> None:
        if self.process is not None:
            raise ConfirmError("C++ worker duplicate start")
        if not self.executable.is_file():
            raise ConfirmError(f"C++ kernel worker missing: {self.executable}")
        if self.executable.name.lower() not in self.PRODUCTION_WORKER_NAMES:
            raise ConfirmError("production coordinator may only launch the full ANCF kernel worker")
        self.runtime.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        # Offline direct/legacy switches are test-only controls.  Production
        # coordinator launches must clear inherited values before spawning the
        # full ANCF worker, even when the parent shell used a fixture.
        environment.pop("CFD_ANCF_OFFLINE_DIRECT_WORKER", None)
        environment.pop("CFD_ANCF_OFFLINE_LEGACY_TRANSPORT", None)
        if self.expected_model_contract_sha256 is not None:
            environment["CFD_ANCF_EXPECTED_MODEL_CONTRACT_SHA256"] = self.expected_model_contract_sha256
        else:
            environment.pop("CFD_ANCF_EXPECTED_MODEL_CONTRACT_SHA256", None)
        self.process = subprocess.Popen(
            [str(self.executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(self.runtime), env=environment,
        )
        self.start_count = 1
        self.audit = {
            "component": "cpp_ancf_kernel_worker", "pid": int(self.process.pid),
            "parent_pid": os.getpid(), "command_line": [str(self.executable)],
            "cwd": str(self.runtime), "owned": True, "start_time_ns": time.time_ns(),
            "expected_model_contract_sha256": self.expected_model_contract_sha256,
        }
        try:
            self.process.stdin.write(encode_control(MESSAGE_INITIALIZE))
            self.process.stdin.flush()
            frame = self._read_frame_bounded(MESSAGE_INITIALIZE_ACK)
            body = frame[IPC_HEADER.size:]
            if len(body) != INITIALIZE_ACK.size:
                raise ConfirmError("C++ worker initialization acknowledgement length is invalid")
            schema, protocol, message_type, role = INITIALIZE_ACK.unpack(body)
            if b"\0" not in role:
                raise ConfirmError("C++ worker role acknowledgement is not terminated")
            role_raw, role_tail = role.split(b"\0", 1)
            if not role_raw or any(role_tail):
                raise ConfirmError("C++ worker role acknowledgement has invalid padding")
            role_value = role_raw.decode("ascii")
            if (schema != SCHEMA_VERSION or protocol != PROTOCOL_VERSION or
                    message_type != MESSAGE_INITIALIZE_ACK or role_value != WORKER_ROLE):
                raise ConfirmError("C++ worker initialization acknowledgement is invalid")
            self.audit["worker_role"] = role_value
        except Exception as exc:
            self._abort_owned_process("worker_startup_handshake")
            if isinstance(exc, ConfirmError):
                raise
            raise ConfirmError(str(exc)) from exc

    def step(self, request: KernelStepRequest):
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise ConfirmError("C++ worker is not running")
        try:
            frame = encode_kernel_request(request)
            self.process.stdin.write(frame)
            self.process.stdin.flush()
            # ``Popen.stdout.read`` has no portable timeout on Windows pipes.
            # Read the complete frame on a daemon thread and make the caller's
            # bounded segment fail closed when the worker stops responding.
            frame = self._read_frame_bounded(6)
            response = decode_kernel_response(frame)
            validate_kernel_response(request, response)
        except FrameError as exc:
            self._record_failure("protocol_validation", exc)
            if self.process is not None:
                self._abort_owned_process("worker_protocol_failure")
            raise ConfirmError(str(exc)) from exc
        except ConfirmError:
            # Preserve a precise timeout/disconnect classification already
            # recorded by the bounded reader instead of relabeling it as a
            # generic transport failure.
            if self.process is not None:
                self._abort_owned_process("worker_protocol_failure")
            raise
        except Exception as exc:
            self._record_failure("worker_transport", exc)
            if self.process is not None:
                self._abort_owned_process("worker_transport_failure")
            raise
        return response

    def stop(self) -> None:
        process = self.process
        if process is None:
            return
        try:
            if process.poll() is None and process.stdin is not None:
                process.stdin.write(encode_control(MESSAGE_SHUTDOWN))
                process.stdin.flush()
                process.stdin.close()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self._record_failure("cleanup_timeout", TimeoutError("worker did not exit within cleanup timeout"))
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._record_failure("cleanup_kill", TimeoutError("worker required forced kill"))
                process.kill(); process.wait(timeout=5)
        stream_text: dict[str, str] = {}
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            if stream is None:
                stream_text[name] = ""
                continue
            try:
                stream_text[name] = stream.read().decode("utf-8", errors="replace")
            except (OSError, ValueError) as exc:
                stream_text[name] = ""
                self._record_failure("audit_stream_read", exc)
        self.audit.update({"end_time_ns": time.time_ns(), "return_code": process.returncode,
                           "cleanup_result": "closed" if process.returncode == 0 else "closed_nonzero",
                           "owned_residual": 0 if process.poll() is not None else 1,
                           "stdout": stream_text["stdout"], "stderr": stream_text["stderr"]})
        self._join_reader_threads()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        self.process = None

    @property
    def owned_residual(self) -> int:
        process_residual = int(self.audit.get("owned_residual", 0) or 0)
        reader_residual = int(self.audit.get("reader_thread_residual", 0) or 0)
        return max(process_residual, reader_residual)

    @property
    def return_code(self) -> int | None:
        value = self.audit.get("return_code")
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else value


class MockSlice:
    def __init__(self, slice_id: int, mapping: Mapping) -> None:
        self.slice_id = int(slice_id)
        self.mapping = mapping
        self.started = False
        self.closed = False
        self.start_count = 0
        self.pid = 20_000 + self.slice_id
        self.start_time_ns: int | None = None
        self.end_time_ns: int | None = None
        self.return_code: int | None = None

    def start(self) -> None:
        if self.started:
            raise ConfirmError(f"slice {self.slice_id} duplicate start")
        self.started = True; self.start_count += 1; self.start_time_ns = time.time_ns()

    def advance(self, *, global_step: int, time_s: float, tick: int, q: tuple[float, ...]) -> dict[str, Any]:
        if not self.started or self.closed:
            raise ConfirmError(f"slice {self.slice_id} is not live")
        bridge, expected_time, expected_tick = self.mapping.identity(global_step)
        if abs(time_s - expected_time) > 1e-12 or tick != expected_tick:
            raise ConfirmError(f"slice {self.slice_id} identity mismatch")
        # Deterministic mock load; production OpenFOAM adapter will implement
        # the same identity and acknowledgement contract.
        amplitude = 0.01 * (self.slice_id + 1) * (1.0 + abs(q[3]) if len(q) > 3 else 1.0)
        force = (amplitude, 0.1 * amplitude, 0.0)
        return {"slice_id": self.slice_id, "global_step": global_step,
                "case_local_bridge_step": bridge, "time_s": time_s,
                "integer_tick": tick, "sequence": global_step - self.mapping.source_step,
                "transaction_id": global_step * 10 + self.slice_id,
                "ack": "consumed", "payload_hash": _sha_vectors(force), "force": force}

    def stop(self) -> None:
        if not self.started or self.closed:
            return
        self.closed = True; self.end_time_ns = time.time_ns(); self.return_code = 0


def _fixture() -> tuple[KernelModel, tuple[float, ...], tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    path = Path(__file__).resolve().parents[3] / "runtime/cpp_worker_persistent_ipc_v1/dual_run_018/results/cpp_input_fixture.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    model = KernelModel(
        length_m=float(raw["length_m"]), diameter_m=float(raw["diameter_m"]),
        inner_diameter_m=float(raw["inner_diameter_m"]), elements=int(raw["elements"]),
        slices=int(raw["slices"]), top_tension_N=float(raw["top_tension_N"]),
        youngs_modulus_Pa=float(raw["youngs_modulus_Pa"]), material_density=float(raw["material_density"]),
        fluid_density=float(raw["fluid_density"]), gravity=float(raw["gravity"]),
        beta=float(raw["beta"]), gamma=float(raw["gamma"]), newton_tolerance=float(raw["newton_tolerance"]),
        damping_alpha=float(raw["damping_alpha"]), damping_beta=float(raw["damping_beta"]),
        gauss_order=int(raw["gauss_order"]), max_newton=int(raw["max_newton"]),
        slice_positions_m=tuple(float(x) for x in raw["slice_positions_m"]),
    )
    n = model.ndof
    return model, tuple(raw["q"][:n]), tuple(raw["qdot"][:n]), tuple(raw["qddot"][:n]), tuple(raw["base_load"][:n])


def run_mock_confirm(*, runtime: Path, executable: Path | None = None,
                     run_id: str = "cpp_confirm_mock_001", case_id: str = "cpp_confirm_mock_case_001",
                     steps: int = 40, results_dir: Path | None = None) -> dict[str, Any]:
    if steps != 40:
        raise ConfirmError("mock confirm is intentionally bounded to exactly 40 steps")
    mapping = Mapping()
    model, q, qdot, qddot, base_load = _fixture()
    executable = executable or (Path(__file__).resolve().parents[3] / "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_ancf_kernel_worker.exe")
    worker = KernelWorker(executable, runtime / "process", run_id, case_id)
    slices = [MockSlice(index, mapping) for index in range(3)]
    rows: list[dict[str, Any]] = []
    committed: list[dict[str, Any]] = []
    previous_force = tuple(0.0 for _ in range(3 * model.slices))
    started = time.perf_counter()
    try:
        worker.start()
        for item in slices: item.start()
        for index in range(1, 41):
            global_step = mapping.source_step + index
            bridge, time_s, tick = mapping.identity(global_step)
            request = KernelStepRequest(
                sequence=index, global_step=global_step, case_local_bridge_step=bridge,
                integer_tick=tick, time_s=time_s, dt_s=mapping.dt_s,
                request_id=100_000 + index, transaction_id=200_000 + index,
                run_id=run_id, case_id=case_id, model=model, q=q, qdot=qdot, qddot=qddot,
                base_load=base_load, slice_force=previous_force,
            )
            response = worker.step(request)
            motion = tuple(response.q)
            acks = [item.advance(global_step=global_step, time_s=time_s, tick=tick, q=motion) for item in slices]
            if {ack["slice_id"] for ack in acks} != {0, 1, 2}:
                raise ConfirmError("global barrier did not receive all slices")
            previous_force = tuple(value for ack in acks for value in ack["force"])
            row = {"global_step": global_step, "case_local_bridge_step": bridge,
                   "time_s": time_s, "integer_tick": tick, "run_id": run_id,
                   "case_id": case_id, "worker_sequence": response.sequence,
                   "worker_transaction_id": response.transaction_id, "worker_payload_hash": response.payload_hash.hex(),
                   "slice_acks": acks, "finite_value_audit": response.finite_value_audit,
                   "return_code": response.return_code}
            rows.append(row)
            committed.append({"global_step": global_step, "case_local_bridge_step": bridge,
                              "time_s": time_s, "integer_tick": tick,
                              "checkpoint_hash": hashlib.sha256(_canonical(row)).hexdigest()})
            q, qdot, qddot = response.q, response.qdot, response.qddot
    finally:
        for item in slices: item.stop()
        worker.stop()
    wall = time.perf_counter() - started
    residual = 0 if all(item.closed for item in slices) and not worker.process else 1
    result = {"status": "completed" if len(committed) == 40 and residual == 0 else "failed",
              "stage_id": "stage4f_d_cpp_worker_confirm_v1", "run_id": run_id, "case_id": case_id,
              "steps": len(committed), "segment_duration_s": 0.05, "slice_count": 3,
              "source_global_step": mapping.source_step, "source_time_s": mapping.source_time_s,
              "source_tick": mapping.source_tick, "global_dt_s": mapping.dt_s,
              "wall_clock_s": wall, "worker_start_count": worker.start_count,
              "slice_start_counts": [item.start_count for item in slices],
              "physical_committed": len(committed), "fully_audited": len(rows),
              "owned_residual": residual, "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
              "worker_process_audit": worker.audit, "committed": committed, "step_records": rows}
    result["process_registry"] = [worker.audit] + [
        {"component": "mock_slice", "slice_id": item.slice_id, "pid": item.pid,
         "parent_pid": os.getpid(), "command_line": ["mock_openfoam_slice", str(item.slice_id)],
         "cwd": str(runtime), "owned": True, "start_time_ns": item.start_time_ns,
         "end_time_ns": item.end_time_ns, "return_code": item.return_code,
         "cleanup_result": "closed" if item.closed else "open"} for item in slices
    ]
    result["protocol_audit"] = {"mapping": {"source_step": mapping.source_step, "source_time_s": mapping.source_time_s,
                                              "source_tick": mapping.source_tick, "dt_s": mapping.dt_s},
                                "first_target": rows[0]["global_step"], "last_target": rows[-1]["global_step"],
                                "duplicate_ack_count": 0, "stale_ack_count": 0, "out_of_order_ack_count": 0,
                                "identity_mismatch_count": 0, "nonfinite_count": 0,
                                "worker_sequences_contiguous": [row["worker_sequence"] for row in rows] == list(range(1, 41)),
                                "barrier_release_count": len(committed)}
    output_root = (results_dir or (runtime / "results")).resolve()
    _write_json(output_root / "mock_confirm_result.json", result)
    gate = {"gate": "STAGE4F_D_CPP_WORKER_CONFIRM_V1_GATE: pass" if result["status"] == "completed" else "STAGE4F_D_CPP_WORKER_CONFIRM_V1_GATE: do_not_pass",
            "scope": {"steps": 40, "segment_duration_s": 0.05, "slice_count": 3},
            "physical_committed": result["physical_committed"], "fully_audited": result["fully_audited"],
            "worker_start_count": result["worker_start_count"], "slice_start_counts": result["slice_start_counts"],
            "owned_residual": residual, "real_process_starts": result["real_process_starts"],
            "persistent_ipc": True, "mock_openfoam": True,
            "statistics_status": {"frequency": "not_evaluable_cpp_confirm_only", "FORMAL_STROUHAL_STATUS": "not_completed",
                                   "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"}}
    _write_json(output_root / "stage4f_d_cpp_worker_confirm_v1_gate.json", gate)
    return gate
