"""Run the isolated C++ ANCF modal/free-vibration qualification.

This program deliberately rebuilds the canonical static load from the C++
kernel.  The retained historical fixture supplies physical model parameters
only; its ``base_load`` vector is not assumed to be a static-load contract.
No CFD, MATLAB, preCICE, or historical runtime is started or modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
DEFAULT_BINARY = ROOT / "runtime/solver_validation_v3/ancf_modal_build/cfd_ancf_ancf_modal_free_diagnostic"
RESULT = ROOT / "results/ancf_free_decay/undamped/cpp_50m_fixture_v2.json"
RAW = ROOT / "results/ancf_free_decay/undamped/cpp_50m_fixture_v2.stdout.txt"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_line(line: str) -> dict[str, float | int | str]:
    tokens = line.split()
    if not tokens:
        return {}
    result: dict[str, float | int | str] = {"record": tokens[0]}
    if len(tokens) % 2 == 0:
        raise ValueError(f"malformed diagnostic line: {line}")
    for index in range(1, len(tokens), 2):
        key, value = tokens[index], tokens[index + 1]
        if key in result:
            raise ValueError(f"duplicate field {key}")
        try:
            number = float(value)
        except ValueError:
            result[key] = value
        else:
            if not math.isfinite(number):
                raise ValueError(f"non-finite {key}")
            result[key] = int(number) if number.is_integer() else number
    return result


def parse_pairs(tokens: list[str], *, start: int) -> dict[str, float | int | str]:
    if (len(tokens) - start) % 2:
        raise ValueError(f"malformed diagnostic tokens: {' '.join(tokens)}")
    result: dict[str, float | int | str] = {}
    for index in range(start, len(tokens), 2):
        key, value = tokens[index], tokens[index + 1]
        if key in result:
            raise ValueError(f"duplicate field {key}")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"non-finite {key}")
        result[key] = int(number) if number.is_integer() else number
    return result


def dominant_frequency(times: np.ndarray, values: np.ndarray) -> float:
    if len(times) < 8:
        raise ValueError("insufficient free-vibration samples")
    dt = np.diff(times)
    if not np.allclose(dt, dt[0], rtol=1.0e-8, atol=1.0e-10):
        raise ValueError("nonuniform free-vibration samples")
    indices = np.arange(len(values), dtype=float)
    trend = np.polyval(np.polyfit(indices, values, 1), indices)
    spectrum = np.abs(np.fft.rfft(values - trend))
    if len(spectrum) < 2:
        raise ValueError("empty spectrum")
    return float(np.fft.rfftfreq(len(values), float(dt[0]))[int(np.argmax(spectrum[1:]) + 1)])


def build_input(fixture: dict[str, Any], *, duration_s: float, dt_s: float, output_every: int, perturbation_m: float) -> str:
    required = (
        "length_m", "diameter_m", "inner_diameter_m", "elements", "slices", "top_tension_N",
        "youngs_modulus_Pa", "material_density", "fluid_density", "gravity", "beta", "gamma",
        "newton_tolerance", "gauss_order", "max_newton", "slice_positions_m",
    )
    missing = [key for key in required if key not in fixture]
    if missing:
        raise ValueError(f"fixture missing required model fields: {missing}")
    values = (
        fixture["length_m"], fixture["diameter_m"], fixture["inner_diameter_m"], fixture["elements"], fixture["slices"],
        fixture["top_tension_N"], fixture["youngs_modulus_Pa"], fixture["material_density"], fixture["fluid_density"],
        fixture["gravity"], dt_s, fixture["beta"], fixture["gamma"], fixture["newton_tolerance"], fixture["gauss_order"],
        5, fixture["max_newton"], duration_s, perturbation_m, output_every,
    )
    positions = fixture["slice_positions_m"]
    if not isinstance(positions, list) or len(positions) != int(fixture["slices"]):
        raise ValueError("fixture slice positions are incomplete")
    return " ".join(str(value) for value in (*values, *positions)) + "\n"


def run(binary: Path, payload: str) -> str:
    if not binary.is_file():
        raise FileNotFoundError(f"diagnostic binary missing: {binary}; build the explicit C++ target first")
    drive = binary.drive.rstrip(":").lower()
    if len(drive) != 1:
        raise ValueError(f"C++ diagnostic must be on a mounted Windows drive: {binary}")
    linux_binary = "/mnt/" + drive + binary.as_posix()[2:]
    result = subprocess.run(
        ["wsl.exe", "--", linux_binary], input=payload, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"C++ modal/free diagnostic failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def parse_output(stdout: str) -> dict[str, Any]:
    meta: dict[str, Any] | None = None
    modes: list[dict[str, Any]] = []
    shapes: dict[int, list[float]] = {}
    samples: list[dict[str, Any]] = []
    summary: dict[str, Any] | None = None
    for raw in stdout.splitlines():
        tokens = raw.split()
        if not tokens:
            continue
        if tokens[0] == "shape":
            if len(tokens) < 3:
                raise ValueError("malformed shape record")
            mode = int(tokens[1])
            shapes[mode] = [float(value) for value in tokens[2:]]
            continue
        if tokens[0] == "mode":
            if len(tokens) < 4:
                raise ValueError("malformed mode record")
            parsed = parse_pairs(tokens, start=2)
            parsed["mode"] = int(tokens[1])
            modes.append(parsed)
            continue
        parsed = parse_line(raw)
        record = parsed.pop("record")
        if record == "meta":
            if meta is not None:
                raise ValueError("duplicate meta")
            meta = parsed
        elif record == "sample":
            samples.append(parsed)
        elif record == "summary":
            if summary is not None:
                raise ValueError("duplicate summary")
            summary = parsed
        else:
            raise ValueError(f"unexpected C++ output record {record}")
    if meta is None or len(modes) != 6 or len(samples) < 8 or summary is None:
        raise ValueError("incomplete C++ modal/free diagnostic output")
    for index, mode in enumerate(modes, start=1):
        if int(mode.get("mode", 0)) != index or index not in shapes:
            raise ValueError("mode/shape identity failure")
        mode["normalized_nodal_y_shape"] = shapes[index]
    return {"meta": meta, "modes": modes, "samples": samples, "summary": summary}


def analyze(parsed: dict[str, Any], *, slice_count: int) -> dict[str, Any]:
    samples = parsed["samples"]
    time = np.asarray([float(row["time_s"]) for row in samples], dtype=float)
    result: dict[str, Any] = {"slice_observables": {}, "modal_coordinate_1_frequency_hz": dominant_frequency(time, np.asarray([float(row["modal_coordinate_1"]) for row in samples]))}
    for index in range(slice_count):
        y = np.asarray([float(row[f"y_{index + 1}"]) for row in samples], dtype=float)
        vy = np.asarray([float(row[f"vy_{index + 1}"]) for row in samples], dtype=float)
        result["slice_observables"][f"slice_{index:04d}"] = {
            "y_demeaned_rms_m": float(np.sqrt(np.mean((y - np.mean(y)) ** 2))),
            "y_peak_to_peak_m": float(np.ptp(y)),
            "y_dominant_frequency_hz": dominant_frequency(time, y),
            "vy_rms_mps": float(np.sqrt(np.mean(vy ** 2))),
        }
    energies = np.asarray([float(row["incremental_total_J"]) for row in samples], dtype=float)
    result["incremental_energy"] = {
        "minimum_J": float(np.min(energies)), "maximum_J": float(np.max(energies)),
        "relative_span": float((np.max(energies) - np.min(energies)) / max(abs(energies[0]), 1.0e-30)),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--duration-s", type=float, default=20.0)
    parser.add_argument("--dt-s", type=float, default=0.005)
    parser.add_argument("--output-every", type=int, default=10)
    parser.add_argument("--perturbation-m", type=float, default=1.0e-4)
    args = parser.parse_args()
    if RESULT.exists() or RAW.exists():
        raise RuntimeError(f"refusing to overwrite ANCF evidence: {RESULT.parent}")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = build_input(fixture, duration_s=args.duration_s, dt_s=args.dt_s, output_every=args.output_every, perturbation_m=args.perturbation_m)
    stdout = run(args.diagnostic, payload)
    parsed = parse_output(stdout)
    analysis = analyze(parsed, slice_count=int(fixture["slices"]))
    mode_frequency = [float(mode["frequency_hz"]) for mode in parsed["modes"]]
    closest = min(enumerate(mode_frequency, start=1), key=lambda item: abs(item[1] - 0.20))
    result = {
        "schema_version": "solver_validation_v3.ancf_modal_free.2",
        "scope": "offline C++ ANCF-only controlled equilibrium perturbation; zero mapped fluid force",
        "fixture": {"path": str(FIXTURE), "sha256": sha256(FIXTURE), "fields_used": "physical model and slice positions only; legacy base_load intentionally not used"},
        "source": {"kernel_sha256": sha256(ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp"), "diagnostic_sha256": sha256(ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/ancf_modal_free_diagnostic.cpp"), "binary_sha256": sha256(args.diagnostic)},
        "contract": {"dt_s": args.dt_s, "duration_s": args.duration_s, "output_every_steps": args.output_every, "perturbation_m": args.perturbation_m, "damping_alpha": 0.0, "damping_beta": 0.0, "fluid_slice_force": [0.0] * (3 * int(fixture["slices"]))},
        "modal_method": "C++ static_base_load -> C++ static_equilibrium -> C++ internal tangent/mass; transverse y translation and y-slope DOFs; Cholesky-reduced symmetric generalized eigenproblem",
        "matlab_comparison": {"status": "reference_not_available", "reason": "MATLAB was not started by this authorization; no fabricated comparison"},
        "cpp": parsed,
        "analysis": analysis,
        "near_0p20_hz_mode": {"mode": closest[0], "frequency_hz": closest[1], "absolute_difference_hz": abs(closest[1] - 0.20)},
        "real_process_starts": {"CFD": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL_OpenFOAM": 0},
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(stdout, encoding="utf-8")
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(RESULT), "mode_1_hz": mode_frequency[0], "near_0p20_hz": result["near_0p20_hz_mode"], "free_modal_hz": analysis["modal_coordinate_1_frequency_hz"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
