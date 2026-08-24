from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


class DevelopedFlowError(RuntimeError):
    pass


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXED_TEMPLATE = PROJECT_ROOT / "cases" / "openfoam" / "fixed_cylinder"
FLOW_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow"
RESULT_ROOT = PROJECT_ROOT / "results" / "06_developed_flow"
FORCE_RE = re.compile(r"^\s*([0-9.eE+-]+)\s+\(\(([^)]*)\)\s+\(([^)]*)\)")


@dataclass(frozen=True)
class ForceSample:
    time_s: float
    force_N: tuple[float, float, float]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_force_history(path: str | Path) -> list[ForceSample]:
    target = Path(path)
    if not target.is_file():
        raise DevelopedFlowError(f"force history is missing: {target}")
    samples: list[ForceSample] = []
    for line in target.read_text(encoding="utf-8", errors="strict").splitlines():
        match = FORCE_RE.match(line)
        if match is None:
            continue
        try:
            current_time = float(match.group(1))
            pressure = [float(item) for item in match.group(2).split()]
            viscous = [float(item) for item in match.group(3).split()]
        except ValueError as exc:
            raise DevelopedFlowError(f"invalid force row in {target}") from exc
        if len(pressure) != 3 or len(viscous) != 3 or not all(math.isfinite(item) for item in (current_time, *pressure, *viscous)):
            raise DevelopedFlowError(f"non-finite or malformed force row in {target}")
        samples.append(ForceSample(current_time, tuple(pressure[i] + viscous[i] for i in range(3))))
    if len(samples) < 16:
        raise DevelopedFlowError(f"force history has too few rows: {len(samples)}")
    times = [item.time_s for item in samples]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise DevelopedFlowError("force time history is not strictly increasing")
    return samples


def collect_force_history(case: str | Path) -> tuple[list[ForceSample], list[Path]]:
    """Merge force files from independent continuation time directories."""
    root = Path(case) / "postProcessing" / "cylinderForces"
    paths = sorted(root.glob("*/forces.dat"), key=lambda path: float(path.parent.name))
    if not paths:
        raise DevelopedFlowError(f"no force files under {root}")
    by_time: dict[float, ForceSample] = {}
    for path in paths:
        for sample in parse_force_history(path):
            key = round(sample.time_s, 9)
            by_time[key] = sample
    samples = [by_time[key] for key in sorted(by_time)]
    if len(samples) < 16:
        raise DevelopedFlowError(f"merged force history has too few rows: {len(samples)}")
    return samples, paths


def write_force_history_csv(path: Path, samples: Sequence[ForceSample]) -> None:
    lines = ["time_s,force_x_N,force_y_N,force_z_N"]
    lines.extend(f"{item.time_s:.17g},{item.force_N[0]:.17g},{item.force_N[1]:.17g},{item.force_N[2]:.17g}" for item in samples)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def dominant_frequency(times: Sequence[float], values: Sequence[float], *, fmin: float = 0.001, fmax: float | None = None) -> float:
    if len(times) != len(values) or len(times) < 32:
        return 0.0
    t = np.asarray(times, dtype=float)
    y = np.asarray(values, dtype=float)
    dt = float(np.median(np.diff(t)))
    if not math.isfinite(dt) or dt <= 0.0:
        return 0.0
    if fmax is None:
        fmax = 0.5 / dt
    fmax = min(float(fmax), 0.5 / dt)
    if fmax <= fmin:
        return 0.0
    # Remove a linear startup drift before taking the spectrum.  Zero
    # padding improves the frequency estimate without changing the samples.
    x = np.arange(len(y), dtype=float)
    y = y - np.polyval(np.polyfit(x, y, 1), x)
    nfft = max(4096, 1 << int(math.ceil(math.log2(len(y)))))
    spectrum = np.abs(np.fft.rfft(y, n=nfft))
    frequencies = np.fft.rfftfreq(nfft, dt)
    mask = (frequencies >= fmin) & (frequencies <= fmax)
    if not np.any(mask):
        return 0.0
    candidates = np.flatnonzero(mask)
    index = int(candidates[int(np.argmax(spectrum[mask]))])
    # Parabolic interpolation around the peak, when available.
    if 0 < index < len(spectrum) - 1:
        left, center, right = spectrum[index - 1:index + 2]
        denominator = left - 2.0 * center + right
        if abs(denominator) > 1.0e-30:
            index = float(index) + 0.5 * (left - right) / denominator
    return float(index / (nfft * dt))


def _rms(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    return float(np.sqrt(np.mean(array * array)))


def _window_metrics(samples: Sequence[ForceSample], U: float, start: float, end: float, rho: float, D: float, span: float) -> dict[str, Any]:
    selected = [item for item in samples if start - 1.0e-12 <= item.time_s <= end + 1.0e-12]
    if len(selected) < 16:
        raise DevelopedFlowError("stability window has too few force samples")
    times = [item.time_s for item in selected]
    cd = [item.force_N[0] / (0.5 * rho * U * U * D * span) for item in selected]
    cl = [item.force_N[1] / (0.5 * rho * U * U * D * span) for item in selected]
    frequency = dominant_frequency(times, cl, fmin=0.05 * U / D, fmax=0.35 * U / D)
    return {
        "start_time_s": start, "end_time_s": end, "samples": len(selected),
        "mean_Cd": float(np.mean(cd)), "Cd_rms": _rms(cd), "Cl_rms": _rms(cl),
        "Cl_peak_to_peak": float(max(cl) - min(cl)), "lift_frequency_Hz": frequency,
        "St": frequency * D / U if U > 0 else 0.0,
    }


def analyze_force_history(samples: Sequence[ForceSample], *, U: float, rho: float = 1000.0, D: float = 1.0, span: float = 1.0, end_time_s: float | None = None) -> dict[str, Any]:
    if not samples:
        raise DevelopedFlowError("empty force history")
    end = float(end_time_s if end_time_s is not None else samples[-1].time_s)
    all_times = [item.time_s for item in samples]
    all_lift = [item.force_N[1] for item in samples]
    rough_frequency = dominant_frequency(all_times[int(len(samples) * 0.35):], all_lift[int(len(samples) * 0.35):], fmin=0.05 * U / D, fmax=0.35 * U / D)
    if rough_frequency <= 0.0:
        rough_frequency = 0.16 * U / D
    period = 1.0 / rough_frequency
    discard_start = min(max(2.0 * period, 2.0), 0.35 * end)
    available_cycles = max(0.0, (end - discard_start) / period)
    two_periods = 2.0 * period
    window_end = end
    analysis_start = discard_start if end - discard_start >= 4.0 * period else max(0.0, end - 4.0 * period)
    window_2_start = max(analysis_start, window_end - two_periods)
    window_1_end = window_2_start
    window_1_start = max(analysis_start, window_1_end - two_periods)
    window_1 = _window_metrics(samples, U, window_1_start, window_1_end, rho, D, span)
    window_2 = _window_metrics(samples, U, window_2_start, window_end, rho, D, span)
    cd_change = abs(window_2["mean_Cd"] - window_1["mean_Cd"]) / max(abs(window_1["mean_Cd"]), 1.0e-30)
    cl_change = abs(window_2["Cl_rms"] - window_1["Cl_rms"]) / max(abs(window_1["Cl_rms"]), 1.0e-30)
    freq_change = abs(window_2["lift_frequency_Hz"] - window_1["lift_frequency_Hz"]) / max(abs(window_1["lift_frequency_Hz"]), 1.0e-30)
    cl_chunks = np.array_split(np.asarray([item.force_N[1] for item in samples if discard_start <= item.time_s <= end]), 4)
    chunk_rms = [_rms(chunk) for chunk in cl_chunks if len(chunk)]
    monotonic_growth_or_decay = len(chunk_rms) >= 3 and (
        all(b > a * (1.0 + 1.0e-6) for a, b in zip(chunk_rms, chunk_rms[1:]))
        or all(b < a * (1.0 - 1.0e-6) for a, b in zip(chunk_rms, chunk_rms[1:]))
    )
    return {
        "total_runtime_s": end,
        "discarded_startup_transient_s": discard_start,
        "dominant_frequency_Hz": window_2["lift_frequency_Hz"],
        "St": window_2["St"],
        "mean_Cd": window_2["mean_Cd"], "Cd_rms": window_2["Cd_rms"], "Cl_rms": window_2["Cl_rms"],
        "period_s": period, "covered_cycles_after_transient": available_cycles,
        "window_1": window_1, "window_2": window_2,
        "window_relative_changes": {"mean_Cd": cd_change, "Cl_rms": cl_change, "frequency": freq_change},
        "cl_chunk_rms": chunk_rms, "cl_amplitude_monotonic": monotonic_growth_or_decay,
        "criteria": {
            "at_least_four_cycles": available_cycles >= 4.0,
            "mean_Cd_change_le_3_percent": cd_change <= 0.03,
            "Cl_rms_change_le_5_percent": cl_change <= 0.05,
            "frequency_change_le_3_percent": freq_change <= 0.03,
            "Cl_amplitude_not_monotonic": not monotonic_growth_or_decay,
            "St_in_range": 0.12 <= window_2["St"] <= 0.22,
        },
    }


def _replace_scalar(text: str, key: str, value: str) -> str:
    changed, count = re.subn(rf"(?m)^(\s*{re.escape(key)}\s+)[^;]+;", rf"\g<1>{value};", text)
    if count != 1:
        raise DevelopedFlowError(f"expected one {key} entry, found {count}")
    return changed


def prepare_fixed_case(output: Path, U: float, end_time_s: float, run_id: str) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite developed-flow case: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    for name in ("0", "constant", "system"):
        shutil.copytree(FIXED_TEMPLATE / name, output / name)
    shutil.copy2(
        PROJECT_ROOT / "cases" / "openfoam" / "single_dof_free_viv_Ur5p2_developed" / "constant" / "momentumTransport",
        output / "constant" / "momentumTransport",
    )
    control = (output / "system" / "controlDict").read_text(encoding="utf-8")
    control = _replace_scalar(control, "application", "pimpleFoam")
    control = _replace_scalar(control, "endTime", format(end_time_s, ".12g"))
    control = _replace_scalar(control, "writePrecision", "16")
    control = _replace_scalar(control, "timePrecision", "12")
    control = re.sub(r"(?m)^(\s*magUInf\s+)[^;]+;", rf"\g<1>{U:.12g};", control)
    (output / "system" / "controlDict").write_text(control, encoding="utf-8")
    fv_solution_path = output / "system" / "fvSolution"
    fv_solution = fv_solution_path.read_text(encoding="utf-8")
    fv_solution = fv_solution.replace("PISO\n{", "PIMPLE\n{")
    fv_solution = fv_solution.replace("PIMPLE\n{\n    nCorrectors", "PIMPLE\n{\n    nOuterCorrectors          1;\n    nCorrectors")
    if "UFinal" not in fv_solution:
        fv_solution = fv_solution.replace("    U\n    {\n", "    U\n    {\n", 1)
        marker = "    }\n}\n\nPIMPLE"
        fv_solution = fv_solution.replace(marker, "    }\n\n    UFinal\n    {\n        $U;\n        relTol          0;\n    }\n}\n\nPIMPLE", 1)
    fv_solution_path.write_text(fv_solution, encoding="utf-8")
    fv_schemes_path = output / "system" / "fvSchemes"
    fv_schemes = fv_schemes_path.read_text(encoding="utf-8")
    fv_schemes = fv_schemes.replace("div(phi,U)      Gauss linear;", "div(phi,U)      Gauss linearUpwind grad(U);\n    div((nuEff*dev2(T(grad(U))))) Gauss linear;")
    fv_schemes = fv_schemes.replace("default         Gauss linear orthogonal;", "default         Gauss linear corrected;")
    fv_schemes = fv_schemes.replace("default         orthogonal;", "default         corrected;")
    fv_schemes_path.write_text(fv_schemes, encoding="utf-8")
    physical_path = output / "constant" / "physicalProperties"
    physical = physical_path.read_text(encoding="utf-8")
    if "viscosityModel" not in physical:
        physical = physical.replace("// Re =", "viscosityModel  constant;\n\n// Re =", 1)
    physical_path.write_text(physical, encoding="utf-8")
    u_path = output / "0" / "U"
    u_text = re.sub(r"\(\s*1(?:\.0*)?\s+0\s+0\s*\)", f"({U:.12g} 0 0)", u_path.read_text(encoding="utf-8"))
    u_path.write_text(u_text, encoding="utf-8")
    (output / "stage4d_flow_provenance.json").write_text(json.dumps({
        "run_id": run_id, "flow_id": f"re{int(round(U / 0.01))}", "U_mps": U,
        "Re": U / 0.01, "rho_kgpm3": 1000.0, "nu_m2ps": 0.01, "D_m": 1.0,
        "dt_s": 0.0025, "initial_source": "fixed_cylinder_template_0_and_constant_only",
        "final_field_not_copied": True,
    }, indent=2) + "\n", encoding="utf-8")
    return {"case": str(output.resolve()), "U_mps": U, "Re": U / 0.01, "end_time_s": end_time_s, "run_id": run_id}


def _run_openfoam(case: Path, label: str, timeout_s: float = 1800.0) -> dict[str, Any]:
    drive, rest = str(case.resolve()).replace("\\", "/").split(":", 1)
    wcase = f"/mnt/{drive.lower()}{rest}"
    log = case / f"log.{label}"
    executable = "checkMesh" if label.startswith("checkMesh") else ("setFields" if label.startswith("setFields") else "pimpleFoam")
    command = f"source /opt/openfoam10/etc/bashrc; cd '{wcase}'; {executable} > '{log.name}' 2>&1"
    started = time.perf_counter()
    completed = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout_s, check=False)
    if not log.exists():
        log.write_bytes(completed.stdout or b"")
    return {"label": label, "return_code": completed.returncode, "elapsed_s": time.perf_counter() - started, "log": str(log.resolve())}


def run_flow_case(*, flow_id: str, U: float, root: Path = FLOW_ROOT, result_root: Path = RESULT_ROOT, run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or f"stage4d_{flow_id}_{uuid.uuid4().hex[:8]}"
    case = root / flow_id
    result = result_root / flow_id
    result.mkdir(parents=True, exist_ok=True)
    if case.exists():
        force_file = case / "postProcessing" / "cylinderForces" / "0" / "forces.dat"
        numeric_times = []
        for child in case.iterdir():
            try:
                numeric_times.append(float(child.name))
            except ValueError:
                pass
        if force_file.exists() or any(value > 0.0 for value in numeric_times):
            raise FileExistsError(f"developed-flow case already contains solver output: {case}")
        provenance = case / "stage4d_flow_provenance.json"
        prepared = json.loads(provenance.read_text(encoding="utf-8")) if provenance.is_file() else prepare_fixed_case(case, U, 20.0, run_id)
    else:
        prepared = prepare_fixed_case(case, U, 20.0, run_id)
    check = _run_openfoam(case, "checkMesh_20s", timeout_s=300.0)
    if check["return_code"] != 0 or "Mesh OK" not in Path(check["log"]).read_text(encoding="utf-8", errors="replace"):
        raise DevelopedFlowError(f"checkMesh failed for {flow_id}")
    seed = _run_openfoam(case, "setFields_20s", timeout_s=300.0)
    if seed["return_code"] != 0:
        raise DevelopedFlowError(f"setFields failed for {flow_id}")
    runs = [_run_openfoam(case, "pimpleFoam_20s", timeout_s=1800.0)]
    samples, force_paths = collect_force_history(case)
    statistics = analyze_force_history(samples, U=U, end_time_s=samples[-1].time_s)
    while not all(statistics["criteria"].values()) and runs[-1]["return_code"] == 0 and len(runs) < 9:
        current_end = float(samples[-1].time_s)
        if current_end >= 60.0 - 0.0025:
            break
        next_end = min(60.0, current_end + 5.0)
        control_path = case / "system" / "controlDict"
        control = control_path.read_text(encoding="utf-8")
        control = re.sub(r"(?m)^(\s*startFrom\s+)[^;]+;", r"\g<1>latestTime;", control)
        control = _replace_scalar(control, "endTime", format(next_end, ".12g"))
        control_path.write_text(control, encoding="utf-8")
        runs.append(_run_openfoam(case, f"pimpleFoam_{int(round(next_end))}s", timeout_s=1800.0))
        if runs[-1]["return_code"] != 0:
            break
        samples, force_paths = collect_force_history(case)
        if samples[-1].time_s > 60.0 + 1.0e-9:
            raise DevelopedFlowError(f"developed-flow runtime exceeded 60 s for {flow_id}: {samples[-1].time_s}")
        statistics = analyze_force_history(samples, U=U, end_time_s=samples[-1].time_s)
    numeric_dirs = []
    for child in case.iterdir():
        if not child.is_dir():
            continue
        try:
            numeric_dirs.append((float(child.name), child))
        except ValueError:
            continue
    if not numeric_dirs:
        raise DevelopedFlowError(f"no OpenFOAM time directories in {case}")
    final_value, final_dir = max(numeric_dirs, key=lambda item: item[0])
    final_time = final_dir.name
    required = [final_dir / name for name in ("U", "p", "phi", "uniform" / Path("time"))]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise DevelopedFlowError(f"final developed field is incomplete for {flow_id}: {missing}")
    max_cfl = 0.0
    for run in runs:
        text = Path(run["log"]).read_text(encoding="utf-8", errors="replace")
        values = [float(item) for item in re.findall(r"Courant Number mean:\s*[-+0-9.eE]+\s+max:\s*([-+0-9.eE]+)", text)]
        if values:
            max_cfl = max(max_cfl, max(values))
        if any(token in text for token in ("nan", "NaN", "Inf", "FOAM FATAL ERROR")):
            raise DevelopedFlowError(f"non-finite/fatal text in {run['log']}")
    fields = {str(path.relative_to(case)).replace("\\", "/"): sha256_file(path) for path in required}
    force_history_path = result / "force_history.csv"
    write_force_history_csv(force_history_path, samples)
    force_sha = sha256_file(force_history_path)
    physical_identity = {
        "flow_id": flow_id, "U_mps": U, "Re": U / 0.01, "rho_kgpm3": 1000.0,
        "nu_m2ps": 0.01, "D_m": 1.0, "dt_s": 0.0025, "end_time_s": statistics["total_runtime_s"],
        "force_sha256": force_sha, "final_fields": fields,
        "template_hashes": {
            relative: sha256_file(FIXED_TEMPLATE / relative)
            for relative in ("system/controlDict", "system/fvSolution", "system/fvSchemes", "constant/physicalProperties", "constant/polyMesh/points", "0/U", "0/p")
        },
        "openfoam_version": "OpenFOAM-10", "application": "pimpleFoam",
    }
    developed_sha = canonical_sha(physical_identity)
    summary = {**prepared, "flow_id": flow_id, "end_time_s": statistics["total_runtime_s"], "status": "developed" if all(statistics["criteria"].values()) else "blocked", "statistics": statistics, "max_cfl": max_cfl, "checkMesh": check, "solver_runs": runs, "force_files": [str(path.resolve()) for path in force_paths], "force_history_csv": str(force_history_path.resolve()), "force_sha256": force_sha, "final_time_name": final_time, "final_fields": fields, "developed_flow_sha256": developed_sha, "physical_identity": physical_identity}
    (result / f"{flow_id}_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def build_developed_flow_bank(*, root: Path = FLOW_ROOT, result_root: Path = RESULT_ROOT) -> dict[str, Any]:
    result_root.mkdir(parents=True, exist_ok=True)
    records = []
    for flow_id, U in (("re80", 0.8), ("re100", 1.0), ("re120", 1.2)):
        summary_path = result_root / flow_id / f"{flow_id}_summary.json"
        if summary_path.is_file():
            records.append(json.loads(summary_path.read_text(encoding="utf-8")))
        else:
            records.append(run_flow_case(flow_id=flow_id, U=U, root=root, result_root=result_root))
    bank = {
        "status": "passed" if all(item["status"] == "developed" for item in records) else "blocked",
        "flow_ids": [item["flow_id"] for item in records], "flows": records,
        "schema_version": "stage4d-developed-flow-bank-1", "created_utc": time.time(),
        "developed_flow_sha256": canonical_sha([{key: item[key] for key in ("flow_id", "U_mps", "Re", "developed_flow_sha256")} for item in records]),
    }
    (result_root / "developed_flow_bank.json").write_text(json.dumps(bank, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return bank


def audit_developed_flow_identity(summary: Mapping[str, Any], *, case: Path) -> dict[str, Any]:
    """Recompute field/force hashes and reject a modified developed flow."""
    fields = summary.get("final_fields")
    if not isinstance(fields, dict):
        raise DevelopedFlowError("summary has no final_fields")
    actual_fields = {}
    for relative, expected in fields.items():
        path = case / relative
        if not path.is_file() or sha256_file(path) != str(expected):
            raise DevelopedFlowError(f"developed-flow field hash mismatch: {relative}")
        actual_fields[relative] = sha256_file(path)
    force_path = Path(str(summary.get("force_history_csv", "")))
    expected_force = str(summary.get("force_sha256", ""))
    if not force_path.is_file() or sha256_file(force_path) != expected_force:
        raise DevelopedFlowError("developed-flow force history hash mismatch")
    identity = dict(summary.get("physical_identity", {}))
    identity["final_fields"] = actual_fields
    identity["force_sha256"] = expected_force
    recomputed = canonical_sha(identity)
    if recomputed != str(summary.get("developed_flow_sha256", "")):
        raise DevelopedFlowError("developed_flow_sha256 mismatch")
    return {"status": "passed", "developed_flow_sha256": recomputed, "field_count": len(actual_fields), "force_sha256": expected_force}
