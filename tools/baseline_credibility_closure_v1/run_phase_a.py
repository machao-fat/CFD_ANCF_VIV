"""Run the frozen MATLAB--C++ ANCF baseline comparison without CFD."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "validation_matlab_cpp_v1"
MATLAB_SCRIPT = ROOT / "tools" / "baseline_credibility_closure_v1" / "matlab_ancf_cross_reference_v1.m"
MATLAB_RESULT = RESULTS / "matlab_reference.json"
CPP_RAW = RESULTS / "cpp_reference.stdout.txt"
RESULT = RESULTS / "phase_a_result.json"
CPP = ROOT / "runtime" / "baseline_credibility_closure_v1" / "cpp_build" / "cfd_ancf_baseline_cross_diagnostic"
MATLAB = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")

CONTRACT = {
    "L_m": 50.0, "D_m": 1.0, "Di_m": 0.9, "elements": 16, "slices": 3,
    "slice_positions_m": [8.333333333333334, 25.0, 41.666666666666664],
    "E_Pa": 3227125779.2218256, "material_density_kgpm3": 26315.789473684214,
    "fluid_density_kgpm3": 1000.0, "gravity_mps2": 9.81, "top_tension_N": 2179104.0029808935,
    "dt_s": 0.005, "duration_s": 50.0, "beta": 0.25, "gamma": 0.5,
    "newton_tolerance": 1.0e-8, "max_newton": 40, "internal_gauss_order": 3,
    "mass_gauss_order": 5, "static_load_steps": 40, "static_relaxation": 0.8,
    "damping_alpha": 0.0, "damping_beta": 0.0, "perturbation_m": 1.0e-4,
    "output_every_steps": 5,
}
THRESHOLDS = {
    "static_normalized_l2_shape_error": 5.0e-3, "modal_relative_frequency_error": 5.0e-3,
    "modal_mac": 0.95, "dynamic_relative_frequency_error": 5.0e-3,
    "dynamic_rms_relative_error": 2.0e-2, "dynamic_time_series_nrmse": 2.0e-2,
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cxx_payload() -> str:
    values = (
        CONTRACT["L_m"], CONTRACT["D_m"], CONTRACT["Di_m"], CONTRACT["elements"], CONTRACT["slices"],
        CONTRACT["top_tension_N"], CONTRACT["E_Pa"], CONTRACT["material_density_kgpm3"], CONTRACT["fluid_density_kgpm3"],
        CONTRACT["gravity_mps2"], CONTRACT["dt_s"], CONTRACT["beta"], CONTRACT["gamma"], CONTRACT["newton_tolerance"],
        CONTRACT["internal_gauss_order"], CONTRACT["max_newton"], CONTRACT["duration_s"], CONTRACT["output_every_steps"], CONTRACT["perturbation_m"],
    )
    return " ".join(str(value) for value in (*values, *CONTRACT["slice_positions_m"])) + "\n"


def as_wsl(path: Path) -> str:
    return "/mnt/" + path.drive.rstrip(":").lower() + path.as_posix()[2:]


def pairs(tokens: list[str], start: int) -> dict[str, float]:
    if (len(tokens) - start) % 2:
        raise ValueError("odd field count: " + " ".join(tokens))
    result: dict[str, float] = {}
    for index in range(start, len(tokens), 2):
        result[tokens[index]] = float(tokens[index + 1])
    return result


def parse_cpp(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {"static_samples": [], "modes": [], "mode_shapes": {}, "dynamic_samples": [], "core": {}}
    for line in text.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        kind = tokens[0]
        if kind == "meta":
            parsed["meta"] = pairs(tokens, 1)
        elif kind == "static_sample":
            parsed["static_samples"].append(pairs(tokens, 1))
        elif kind == "mode":
            parsed["modes"].append(pairs(tokens, 1))
        elif kind == "mode_shape":
            index = int(float(tokens[2]))
            data = pairs(tokens, 3)
            parsed["mode_shapes"][index] = [data[f"value_{node}"] for node in range(CONTRACT["elements"] + 1)]
        elif kind == "dynamic_sample":
            parsed["dynamic_samples"].append(pairs(tokens, 1))
        elif kind == "core_vector":
            if tokens[1] != "internal_force":
                raise ValueError("unexpected core vector")
            count = int(tokens[2]); values = [float(value) for value in tokens[3:]]
            if len(values) != count:
                raise ValueError("core vector count mismatch")
            parsed["core"]["internal_force"] = values
        elif kind == "core_matrix":
            name, rows, columns = tokens[1], int(tokens[2]), int(tokens[3]); values = [float(value) for value in tokens[4:]]
            if len(values) != rows * columns:
                raise ValueError("core matrix count mismatch")
            parsed["core"][name] = np.asarray(values, dtype=float).reshape(rows, columns).tolist()
        else:
            raise ValueError("unexpected C++ record " + kind)
    if len(parsed["static_samples"]) != 33 or len(parsed["modes"]) != 6 or len(parsed["dynamic_samples"]) != 2001:
        raise ValueError("incomplete C++ diagnostic")
    return parsed


def norm_error(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    difference = candidate - reference
    return {
        "max_absolute": float(np.max(np.abs(difference))),
        "relative_l2": float(np.linalg.norm(difference.ravel()) / max(np.linalg.norm(reference.ravel()), 1.0)),
    }


def dominant_frequency(time: np.ndarray, signal: np.ndarray) -> float:
    step = float(np.median(np.diff(time)))
    values = signal - np.mean(signal)
    spectrum = np.abs(np.fft.rfft(values))
    index = int(np.argmax(spectrum[1:]) + 1)
    return float(np.fft.rfftfreq(values.size, step)[index])


def phase_at_frequency(time: np.ndarray, signal: np.ndarray, frequency: float) -> float:
    return float(np.angle(np.sum((signal - np.mean(signal)) * np.exp(-2j * np.pi * frequency * time))))


def wrap_phase(value: float) -> float:
    return float((value + np.pi) % (2.0 * np.pi) - np.pi)


def compare(matlab: dict[str, Any], cpp: dict[str, Any]) -> dict[str, Any]:
    static_m = matlab["static"]["samples"]
    static_c = cpp["static_samples"]
    if [float(row["s_m"]) for row in static_m] != [float(row["s_m"]) for row in static_c]:
        raise ValueError("static sampling identity mismatch")
    ref = np.asarray([[row[key] for key in ("x_m", "y_m", "z_m")] for row in static_m], dtype=float)
    got = np.asarray([[row[key] for key in ("x_m", "y_m", "z_m")] for row in static_c], dtype=float)
    static_error = norm_error(ref, got)
    static_error["normalized_l2_shape_error"] = float(np.linalg.norm((got-ref).ravel()) / (math.sqrt(ref.shape[0]) * CONTRACT["L_m"]))
    static_error["max_relative_to_length"] = float(np.max(np.abs(got-ref)) / CONTRACT["L_m"])

    modes: list[dict[str, float | int]] = []
    for row_m, row_c in zip(matlab["modal"]["modes"], cpp["modes"]):
        index = int(row_m["index"])
        if index != int(row_c["index"]):
            raise ValueError("mode index mismatch")
        a = np.asarray(row_m["normalized_nodal_y_shape"], dtype=float)
        b = np.asarray(cpp["mode_shapes"][index], dtype=float)
        mac = float((np.dot(a, b) ** 2) / (np.dot(a, a) * np.dot(b, b)))
        frequency_m, frequency_c = float(row_m["frequency_hz"]), float(row_c["frequency_hz"])
        modes.append({"mode": index, "matlab_hz": frequency_m, "cpp_hz": frequency_c,
                      "relative_frequency_error": abs(frequency_c-frequency_m)/max(abs(frequency_m), 1.0e-30), "MAC": mac})

    dynamic_m, dynamic_c = matlab["dynamic"]["samples"], cpp["dynamic_samples"]
    tm = np.asarray([row["time_s"] for row in dynamic_m], dtype=float); tc = np.asarray([row["time_s"] for row in dynamic_c], dtype=float)
    if not np.allclose(tm, tc, rtol=0.0, atol=1.0e-12):
        raise ValueError("dynamic time identity mismatch")
    dynamic: dict[str, Any] = {"slices": {}, "energy": {}}
    for slice_id in range(3):
        y_m = np.asarray([row[f"y_{slice_id}"] for row in dynamic_m], dtype=float); y_c = np.asarray([row[f"y_{slice_id}"] for row in dynamic_c], dtype=float)
        vy_m = np.asarray([row[f"vy_{slice_id}"] for row in dynamic_m], dtype=float); vy_c = np.asarray([row[f"vy_{slice_id}"] for row in dynamic_c], dtype=float)
        frequency_m, frequency_c = dominant_frequency(tm, y_m), dominant_frequency(tc, y_c)
        rms_m, rms_c = float(np.sqrt(np.mean(y_m*y_m))), float(np.sqrt(np.mean(y_c*y_c)))
        nrmse = float(np.sqrt(np.mean((y_c-y_m)**2))/max(rms_m,1.0e-30))
        mid = len(tm)//2; fphase = frequency_m
        phase_early = wrap_phase(phase_at_frequency(tm[:mid],y_c[:mid],fphase)-phase_at_frequency(tm[:mid],y_m[:mid],fphase))
        phase_late = wrap_phase(phase_at_frequency(tm[mid:],y_c[mid:],fphase)-phase_at_frequency(tm[mid:],y_m[mid:],fphase))
        dynamic["slices"][str(slice_id)] = {"frequency_matlab_hz":frequency_m,"frequency_cpp_hz":frequency_c,
            "relative_frequency_error":abs(frequency_c-frequency_m)/max(frequency_m,1.0e-30),"y_rms_matlab_m":rms_m,"y_rms_cpp_m":rms_c,
            "rms_relative_error":abs(rms_c-rms_m)/max(rms_m,1.0e-30),"y_time_series_nrmse":nrmse,
            "vy_time_series_nrmse":float(np.sqrt(np.mean((vy_c-vy_m)**2))/max(float(np.sqrt(np.mean(vy_m*vy_m))),1.0e-30)),
            "phase_difference_early_rad":phase_early,"phase_difference_late_rad":phase_late,"phase_drift_rad":wrap_phase(phase_late-phase_early)}
    e_m = np.asarray([row["incremental_energy_J"] for row in dynamic_m],dtype=float); e_c = np.asarray([row["incremental_energy_J"] for row in dynamic_c],dtype=float)
    dynamic["energy"] = norm_error(e_m,e_c)
    core = {name: norm_error(np.asarray(matlab["core"][m_name],dtype=float),np.asarray(cpp["core"][c_name],dtype=float))
            for name,m_name,c_name in (("mass_matrix","mass_matrix","mass"),("internal_force","internal_force","internal_force"),("tangent_matrix","tangent_matrix","tangent"))}
    failures = []
    if static_error["normalized_l2_shape_error"] > THRESHOLDS["static_normalized_l2_shape_error"]: failures.append("static")
    for row in modes:
        if row["relative_frequency_error"] > THRESHOLDS["modal_relative_frequency_error"] or row["MAC"] < THRESHOLDS["modal_mac"]: failures.append("modal_%d" % row["mode"])
    for sid,row in dynamic["slices"].items():
        if (row["relative_frequency_error"] > THRESHOLDS["dynamic_relative_frequency_error"] or
                row["rms_relative_error"] > THRESHOLDS["dynamic_rms_relative_error"] or
                row["y_time_series_nrmse"] > THRESHOLDS["dynamic_time_series_nrmse"]):
            failures.append("dynamic_"+sid)
    return {"static":static_error,"modal":modes,"dynamic":dynamic,"core":core,"status":"pass" if not failures else "fail","failures":failures}


def main() -> int:
    if any(path.exists() for path in (MATLAB_RESULT, CPP_RAW, RESULT)):
        raise RuntimeError("refusing to overwrite Phase A evidence")
    if not CPP.is_file() or not MATLAB.is_file():
        raise RuntimeError("required C++ diagnostic or MATLAB executable is missing")
    RESULTS.mkdir(parents=True,exist_ok=True)
    cpp_run = subprocess.run(["wsl.exe","--",as_wsl(CPP)],input=cxx_payload(),text=True,encoding="utf-8",capture_output=True,timeout=240,check=False)
    if cpp_run.returncode != 0: raise RuntimeError("C++ diagnostic failed: "+cpp_run.stderr.strip())
    CPP_RAW.write_text(cpp_run.stdout,encoding="utf-8")
    command = "cd('"+ROOT.as_posix()+"'); addpath('"+MATLAB_SCRIPT.parent.as_posix()+"'); matlab_ancf_cross_reference_v1('"+MATLAB_RESULT.as_posix()+"');"
    matlab_log = RESULTS / "matlab_stdout.txt"
    with matlab_log.open("wb") as stream:
        matlab_run = subprocess.run([str(MATLAB),"-batch",command],stdout=stream,stderr=subprocess.STDOUT,timeout=1200,check=False)
    if matlab_run.returncode != 0 or not MATLAB_RESULT.is_file():
        raise RuntimeError("MATLAB reference failed; inspect "+str(matlab_log))
    matlab = json.loads(MATLAB_RESULT.read_text(encoding="utf-8")); cpp = parse_cpp(cpp_run.stdout); comparison = compare(matlab,cpp)
    result = {"schema_version":"baseline_credibility_closure_v1.phase_a.1","status":comparison["status"],"contract":CONTRACT,"thresholds":THRESHOLDS,
        "sources":{"matlab_script_sha256":digest(MATLAB_SCRIPT),"cpp_kernel_sha256":digest(ROOT/"src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp"),"cpp_diagnostic_sha256":digest(ROOT/"src/coupling/cpp_worker_persistent_ipc_v1/ancf_baseline_cross_diagnostic.cpp")},
        "matlab_execution":{"status":"pass","executable":str(MATLAB),"stdout_path":str(RESULTS/"matlab_stdout.txt")},"comparison":comparison,
        "artifacts":{"matlab":str(MATLAB_RESULT),"cpp_raw":str(CPP_RAW)}}
    RESULT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"result":str(RESULT),"mode_1":comparison["modal"][0],"static":comparison["static"]},ensure_ascii=False))
    return 0 if result["status"]=="pass" else 2

if __name__ == "__main__": raise SystemExit(main())
