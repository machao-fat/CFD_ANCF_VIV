"""Refresh derived v2.1 yPlus evidence from already completed fresh cases."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.coupling.stage4e_target_re_pilot_v2.identity_v2 import finite
from .analysis_v2_1 import yplus_history


PROJECT = Path(__file__).resolve().parents[3]
RUN_ID = "20260815T145000000Z_stage4e_b2_a_v2_1_medium_screening"
RESULTS = PROJECT / "results" / "10_stage4e_target_re_pilot_v2_1" / RUN_ID
CASES = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder_v2_1" / RUN_ID
RUNTIME = PROJECT / "runtime" / "stage4e_b2_a_v2_1" / RUN_ID


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(finite(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def warmup_dt_stats(model_case: str) -> tuple[float | None, float | None]:
    log = RUNTIME / "logs" / f"{model_case}__warmup.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    values = [float(value) for value in re.findall(r"deltaT\s*=\s*([-+0-9.eE]+)", text)]
    return (min(values), max(values)) if values else (None, None)


def main() -> None:
    histories: list[dict] = []
    for model, filename in (("laminar", "laminar_medium_statistics.json"), ("kOmegaSST", "sst_medium_statistics.json")):
        path = RESULTS / filename
        item = read_json(path)
        case_name = "high_laminar_medium_v2_1" if model == "laminar" else "high_kOmegaSST_medium_v2_1"
        startup_min_dt, warmup_max_dt = warmup_dt_stats(case_name)
        item["warmup"]["startup_min_dt"] = startup_min_dt
        item["warmup"]["warmup_max_dt"] = warmup_max_dt
        records = item.get("formal_yplus", {}).get("records", [])
        history = yplus_history(CASES / case_name, records)
        item["formal_yplus"] = history
        write_json(path, item)
        warmup_path = RESULTS / ("laminar_warmup_summary.json" if model == "laminar" else "sst_warmup_summary.json")
        warmup = read_json(warmup_path)
        warmup["startup_min_dt"] = startup_min_dt
        warmup["warmup_max_dt"] = warmup_max_dt
        write_json(warmup_path, warmup)
        histories.append({"model": model, "history": history})
    write_json(RESULTS / "formal_yplus_history.json", {"models": histories})
    screening_path = RESULTS / "model_screening_v2_1.json"
    screening = read_json(screening_path)
    for result in screening.get("results", []):
        match = next(item for item in histories if item["model"] == result["model"])
        result["formal_yplus"] = match["history"]
    write_json(screening_path, screening)
    startup_path = RESULTS / "startup_warmup_contract.json"
    startup_contract = read_json(startup_path)
    startup_contract.pop("actual_production_cases", None)
    startup_contract["measured_models"] = {
        "laminar": {"startup_min_dt_s": warmup_dt_stats("high_laminar_medium_v2_1")[0], "warmup_max_dt_s": warmup_dt_stats("high_laminar_medium_v2_1")[1]},
        "kOmegaSST": {"startup_min_dt_s": warmup_dt_stats("high_kOmegaSST_medium_v2_1")[0], "warmup_max_dt_s": warmup_dt_stats("high_kOmegaSST_medium_v2_1")[1]},
    }
    write_json(startup_path, startup_contract)
    actual_cases: dict[str, dict] = {}
    for model, case_name in (("laminar", "high_laminar_medium_v2_1"), ("kOmegaSST", "high_kOmegaSST_medium_v2_1")):
        case = CASES / case_name
        times = sorted([float(path.name) for path in case.iterdir() if path.is_dir() and path.name.replace(".", "", 1).isdigit()])
        size_bytes = sum(path.stat().st_size for path in case.rglob("*") if path.is_file())
        actual_cases[model] = {"actual_time_directory_count": len(times), "actual_case_size_bytes": size_bytes, "actual_latest_time_s": times[-1] if times else None}
    sampling_path = RESULTS / "output_sampling_contract_v2_1.json"
    sampling_contract = read_json(sampling_path)
    sampling_contract["actual_production_cases"] = actual_cases
    write_json(sampling_path, sampling_contract)


if __name__ == "__main__":
    main()
