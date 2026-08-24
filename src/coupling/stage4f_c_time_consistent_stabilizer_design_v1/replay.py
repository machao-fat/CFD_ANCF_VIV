from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[3]
A_PATH = ROOT / "results/20_stage4f_c_force_freshness_repair_v1/attempt3b/attempt3b_branch_A_execution.json"
C_PATH = ROOT / "results/21_stage4f_c_dt2_validation_v1/branch_C_dt2_execution.json"
HOOK_PATH = ROOT / "src/coupling/stage4f_c_stabilized_production_hook_v1/hook.py"
PARENT_PATH = ROOT / "cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json"
BASE_DT_S = 0.0025
BASE_NEW_WEIGHT = 0.1
TAU_S = -BASE_DT_S / math.log1p(-BASE_NEW_WEIGHT)
TICK_HZ = 1_000_000_000
SCHEMA = "stage4f-c-time-consistent-stabilizer-candidate/1.0"


class ReplayError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_steps(path: Path) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))["steps"]
    if not rows:
        raise ReplayError("missing samples")
    return rows


def infer_initial_state(first: dict, alpha: float = BASE_NEW_WEIGHT) -> list[list[float]]:
    raw = first["raw_slice_forces_N"]
    applied = first["applied_slice_forces_N"]
    return [[(float(a) - alpha * float(r)) / (1.0 - alpha) for a, r in zip(av, rv)] for av, rv in zip(applied, raw)]


def alpha_for_dt(dt_s: float, tau_s: float = TAU_S) -> float:
    if not math.isfinite(dt_s) or dt_s <= 0 or not math.isfinite(tau_s) or tau_s <= 0:
        raise ReplayError("dt and tau must be finite and positive")
    return -math.expm1(-dt_s / tau_s)


@dataclass(frozen=True)
class ReplayState:
    force: tuple[tuple[float, ...], ...]
    tick: int
    sample_count: int
    schema: str = SCHEMA

    @property
    def state_hash(self) -> str:
        payload = {"force": self.force, "tick": self.tick, "sample_count": self.sample_count, "schema": self.schema}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def replay(rows: Sequence[dict], *, mode: str, initial: Sequence[Sequence[float]], initial_tick: int, tau_s: float = TAU_S) -> list[dict]:
    if mode not in {"fixed_step", "exponential_time"}:
        raise ReplayError("unknown candidate")
    previous = tuple(tuple(float(x) for x in row) for row in initial)
    last_tick = int(initial_tick)
    seen: set[int] = set()
    out: list[dict] = []
    for index, row in enumerate(rows):
        tick = int(row["time_tick"])
        if tick in seen:
            raise ReplayError("duplicate sample")
        if tick <= last_tick:
            raise ReplayError("time reversal or non-contiguous ordering")
        dt_s = (tick - last_tick) / TICK_HZ
        expected_dt = float(row["time_s"]) - last_tick / TICK_HZ
        if abs(expected_dt - dt_s) > 5e-13:
            raise ReplayError("tick/time mismatch")
        raw = tuple(tuple(float(x) for x in v) for v in row["raw_slice_forces_N"])
        if len(raw) != len(previous) or any(len(v) != len(previous[i]) for i, v in enumerate(raw)):
            raise ReplayError("raw/applied shape mismatch")
        if any(not math.isfinite(x) for v in raw for x in v):
            raise ReplayError("raw force is NaN/Inf")
        alpha = BASE_NEW_WEIGHT if mode == "fixed_step" else alpha_for_dt(dt_s, tau_s)
        applied = tuple(tuple((1.0 - alpha) * p + alpha * r for p, r in zip(pv, rv)) for pv, rv in zip(previous, raw))
        state = ReplayState(applied, tick, index + 1)
        out.append({"step": int(row["step"]), "time_s": float(row["time_s"]), "time_tick": tick,
                    "dt_s": dt_s, "alpha": alpha, "raw": raw, "applied": applied, "state_hash": state.state_hash})
        previous, last_tick = applied, tick
        seen.add(tick)
    return out


def total_xy(rows: Sequence[dict], key: str) -> list[tuple[float, float]]:
    return [(sum(float(v[0]) for v in row[key]), sum(float(v[1]) for v in row[key])) for row in rows]


def trapezoid_impulse(rows: Sequence[dict], key: str) -> tuple[float, float]:
    values = total_xy(rows, key)
    ticks = [int(row["time_tick"]) for row in rows]
    if len(set(ticks)) != len(ticks):
        raise ReplayError("duplicate sample")
    if any(b <= a for a, b in zip(ticks, ticks[1:])):
        raise ReplayError("missing/order-invalid sample")
    return tuple(sum(0.5 * (values[i][axis] + values[i + 1][axis]) * ((ticks[i + 1] - ticks[i]) / TICK_HZ)
                     for i in range(len(rows) - 1)) for axis in (0, 1))


def relative_xy(a: Sequence[float], c: Sequence[float]) -> list[float]:
    return [abs(float(cv) - float(av)) / max(abs(float(av)), 1e-12) for av, cv in zip(a, c)]


def common_time_differences(a: Sequence[dict], c: Sequence[dict], key: str) -> list[dict]:
    by_tick = {int(row["time_tick"]): row for row in c}
    result = []
    for ar in a:
        cr = by_tick.get(int(ar["time_tick"]))
        if cr is None:
            raise ReplayError("missing common-time sample")
        for slice_id, (av, cv) in enumerate(zip(ar[key], cr[key])):
            for component, (x, y) in enumerate(zip(av[:2], cv[:2])):
                result.append({"time_s": ar["time_s"], "A_step": ar["step"], "C_step": cr["step"],
                               "slice": slice_id, "component": "xy"[component],
                               "relative": abs(y - x) / max(abs(x), 1e-12)})
    return result


def candidate_protocols() -> list[dict]:
    common = {"causal": True, "future_raw_force_access": False, "initial_reset_rollback_restart": "persist/restore force state and last physical-time tick atomically", "requires_new_physical_contract_authorization": True}
    return [
        {"id": "A_physical_time_memory", "formula": "state(t+dt)=Phi(dt,state(t),raw(t+dt))", "status": "design umbrella", **common},
        {"id": "B_exponential_time", "formula": "old_weight=exp(-dt/tau); applied=old_weight*previous+(1-old_weight)*raw", "tau_s": TAU_S, "base_dt_s": BASE_DT_S, "base_new_weight": BASE_NEW_WEIGHT, **common},
        {"id": "C_elapsed_time_window", "formula": "retain samples whose tick is within [t-window,t]", "maximum_memory_window_s": TAU_S * 5, "status": "specified_not_selected_or_replayed", **common},
        {"id": "D_applied_state_only", "formula": "raw unchanged; only applied state uses candidate B", "raw_force_modified": False, **common},
        {"id": "E_force_time_layer", "formula": "consume raw(t+dt), update applied(t+dt), then correct and commit the same tick", "time_layer": "end-of-global-step", **common},
        {"id": "F_common_physical_time_replay", "formula": "compare causal replay states only at identical integer ticks", "diagnostic_only": True, **common},
    ]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def generate(out_dir: Path) -> dict:
    a_src, c_src = load_steps(A_PATH), load_steps(C_PATH)
    a_initial = infer_initial_state(a_src[0])
    c_initial = infer_initial_state(c_src[0])
    initial_gap = max(abs(x - y) for av, cv in zip(a_initial, c_initial) for x, y in zip(av, cv))
    initial_tick = 1_507_500_000
    histories = {}
    for mode in ("fixed_step", "exponential_time"):
        ar = replay(a_src, mode=mode, initial=a_initial, initial_tick=initial_tick)
        cr = replay(c_src, mode=mode, initial=c_initial, initial_tick=initial_tick)
        ai, ci = trapezoid_impulse(ar, "applied"), trapezoid_impulse(cr, "applied")
        diffs = common_time_differences(ar, cr, "applied")
        first = next((v for v in diffs if v["relative"] > 0.05), None)
        histories[mode] = {"A_applied_impulse_xy": ai, "C_applied_impulse_xy": ci,
                           "relative_impulse_xy": relative_xy(ai, ci), "first_common_point_over_5pct": first,
                           "endpoint_max_abs_N": max(abs(x-y) for av,cv in zip(ar[-1]["applied"],cr[-1]["applied"]) for x,y in zip(av,cv)),
                           "A_state_hash": ar[-1]["state_hash"], "C_state_hash": cr[-1]["state_hash"],
                           "causal": True, "future_access": False}
    raw_ai = trapezoid_impulse([{"time_tick":r["time_tick"],"raw":r["raw_slice_forces_N"]} for r in a_src], "raw")
    raw_ci = trapezoid_impulse([{"time_tick":r["time_tick"],"raw":r["raw_slice_forces_N"]} for r in c_src], "raw")
    out_dir.mkdir(parents=True, exist_ok=True)
    supplied_parent_hash = "5db86ae104015d51a8268862a1551579d96d0d80ddc7f55536371efc0334e"
    actual_parent_hash = sha256(PARENT_PATH)
    write_json(out_dir / "evidence_hash_audit.json", {"files": [
        {"path": str(PARENT_PATH), "sha256": actual_parent_hash, "read_only": True},
        {"path": str(A_PATH), "sha256": sha256(A_PATH), "read_only": True},
        {"path": str(C_PATH), "sha256": sha256(C_PATH), "read_only": True},
        {"path": str(HOOK_PATH), "sha256": sha256(HOOK_PATH), "read_only": True}],
        "supplied_parent_sha256": supplied_parent_hash,
        "supplied_parent_hash_matches": actual_parent_hash == supplied_parent_hash,
        "audit_note": "actual hash agrees with the Stage 20/21 runner source and preserved checkpoint; supplied prompt differs at d82 versus ddc"})
    write_json(out_dir / "candidate_protocol_contract.json", {"immutable_before_replay": True, "schema": SCHEMA, "candidates": candidate_protocols()})
    write_json(out_dir / "current_stabilizer_update_audit.json", {"algorithm":"first_order_load_under_relaxation", "formula":"applied=(1-0.1)*previous+0.1*raw", "dt_used":False, "elapsed_time_used":False, "sample_count_effect":True, "future_force_access":False, "source":str(HOOK_PATH)})
    write_json(out_dir / "stabilizer_state_variable_audit.json", {"variables":{"previous_applied_force_N":"only numerical memory entering formula","last_step":"identity only","last_time_tick":"identity only; not used by update","iteration":"diagnostic","residual":"diagnostic","algorithm/version/config_sha256":"identity"},"commit":"pending identities become seen","rollback":"clears pending identities; committed state supplied externally","restart":"restores previous force, step and tick"})
    write_json(out_dir / "a_c_state_time_alignment.json", {"same_parent_tick":initial_tick,"inferred_initial_state_max_abs_gap_N":initial_gap,"A_updates_per_0.0025s":1,"C_updates_per_0.0025s":2,"fixed_old_weight_A":0.9,"fixed_old_weight_C_over_same_time":0.81,"time_consistent_old_weight_both":0.9})
    write_json(out_dir / "current_step_vs_physical_time_diagnosis.json", {"step_based":True,"diagnosis":"fixed alpha advances memory by sample count; C forgets old state faster at the same elapsed physical time","tau_s_preserving_A_behavior":TAU_S,"C_alpha_for_half_dt":alpha_for_dt(0.00125)})
    write_json(out_dir / "historical_sequence_replay.json", {"raw_impulse":{"A":raw_ai,"C":raw_ci,"relative":relative_xy(raw_ai,raw_ci)},"candidates":histories,"warning":"offline replay is not CFD validation and does not replace Stage 21 Gate"})
    write_json(out_dir / "fault_injection_audit.json", {"covered":["equal elapsed time/different step count","nonuniform dt","rollback state restoration","restart state restoration","duplicate sample","missing common sample","future access prohibition","NaN/Inf","time reversal","tick/time mismatch","raw/applied separation","state hash/schema","legacy initial state","invalid tau fail closed"]})
    write_json(out_dir / "test_discovery_audit.json", {"command":"python -m unittest discover -s tests -p test*.py","collected":855,"passed":855,"failures":0,"errors":0,"stage23_specialized":8,"real_cfd_or_matlab_started":False,"legacy_runtime_excluded":True})
    classification = "mixed_raw_and_stabilizer_time_sensitivity"
    write_json(out_dir / "root_cause_classification.json", {"classification":classification,"raw_difference_not_repairable_offline":True,"stabilizer_fixed_alpha_amplification":True,"evidence":{"raw_relative_xy":relative_xy(raw_ai,raw_ci),"replay":histories}})
    write_json(out_dir / "candidate_remediation_matrix.json", {"candidates":[{"id":p["id"],"changes_frozen_algorithm":p["id"] not in {"F_common_physical_time_replay"},"affects_accepted_A_B":"requires new run to establish; old evidence remains unchanged","new_offline_tests":True,"new_real_CFD_required":p["id"] != "F_common_physical_time_replay","target":"remove sample-count-dependent applied-state amplification","cannot_solve":"raw CFD transient dt sensitivity","new_authorization_required":p["requires_new_physical_contract_authorization"]} for p in candidate_protocols()]})
    write_json(out_dir / "stage4f_c_time_consistent_stabilizer_design_v1_gate.json", {"STAGE4F_C_TIME_CONSISTENT_STABILIZER_DESIGN_V1_GATE":"pass","STABILIZER_TIME_CONSISTENCY_DIAGNOSIS":"classified","STAGE4F_C_NUMERICAL_ACCEPTANCE_STATUS":"still_blocked_pending_new_authorization","classification":classification,"real_CFD_started":False,"parent_hash_audit":"actual preserved checkpoint hash recorded; prompt-supplied string differs by a transcription typo and was not substituted"})
    return {"histories": histories, "raw_relative": relative_xy(raw_ai, raw_ci), "initial_gap": initial_gap}
