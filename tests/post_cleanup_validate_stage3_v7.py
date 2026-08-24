"""Read-only validation of critical v7 artifacts after workspace cleanup."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    checks = {}

    metrics = ROOT / "results/04_continuous_fsi/stage3_final_metrics_v7.json"
    py_tests = ROOT / "results/04_continuous_fsi/stage3_v7_test_results.json"
    matlab_tests = ROOT / "results/04_continuous_fsi/stage3_v7_matlab_test_results.json"
    figure_validation = ROOT / "results/04_continuous_fsi/stage3_v7_figure_validation.json"
    checks["v7_metrics_json"] = metrics.exists()
    checks["python_test_json"] = py_tests.exists()
    checks["matlab_test_json"] = matlab_tests.exists()
    checks["figure_validation_json"] = figure_validation.exists()

    if metrics.exists():
        payload = load_json(metrics)
        checks["stage3_not_falsely_closed"] = payload.get("stage3_fully_passed") is False
        checks["stage4_not_falsely_opened"] = payload.get("eligible_for_stage4_prototype") is False
    if py_tests.exists():
        payload = load_json(py_tests)
        checks["python_regression_passed"] = payload.get("returncode") == 0 and payload.get("tests_run") == payload.get("passed") and payload.get("passed") > 0
    if matlab_tests.exists():
        payload = load_json(matlab_tests)
        checks["matlab_regression_passed"] = payload.get("failed", 1) == 0 and payload.get("passed") == payload.get("total")
    if figure_validation.exists():
        payload = load_json(figure_validation)
        counts = payload.get("summary", {}).get("counts", {})
        checks["strict_figures_ready"] = payload.get("strict_ready") is True and payload.get("summary", {}).get("ready") is True and counts.get("FAIL", 1) == 0

    checkpoint_paths = {
        "Ur4": ROOT / "results/04_sdof_corrected_campaign/Ur4_v6_to140/sdof_checkpoint.json",
        "Ur5p2": ROOT / "results/04_sdof_corrected_campaign/Ur5p2_v6_retry_to130/sdof_checkpoint.json",
        "Ur8": ROOT / "results/04_sdof_corrected_campaign/Ur8p0_v7_to260/sdof_checkpoint.json",
    }
    checkpoint_records = {}
    for name, path in checkpoint_paths.items():
        record = {"path": str(path.absolute()), "exists": path.exists(), "json_readable": False, "cfd_time_directory_exists": False}
        if path.exists():
            payload = load_json(path)
            record["json_readable"] = True
            state = payload.get("state", {})
            record["time"] = state.get("time_s", payload.get("time"))
            record["step"] = state.get("step", payload.get("step"))
            cfd_dir = payload.get("cfd", {}).get("time_directory")
            if cfd_dir:
                cfd_path = Path(cfd_dir)
                if not cfd_path.is_absolute():
                    cfd_path = ROOT / cfd_path
                record["cfd_time_directory"] = str(cfd_path.absolute())
                record["cfd_time_directory_exists"] = cfd_path.exists()
        checkpoint_records[name] = record
    checks["critical_checkpoints_readable"] = all(
        item["exists"] and item["json_readable"] for item in checkpoint_records.values()
    )

    template_paths = [
        ROOT / "cases/openfoam/single_slice_ancf_fsi/0",
        ROOT / "cases/openfoam/single_slice_ancf_fsi/constant",
        ROOT / "cases/openfoam/single_slice_ancf_fsi/system",
        ROOT / "cases/openfoam/single_dof_free_v6_to200/0",
        ROOT / "cases/openfoam/single_dof_free_v6_to200/constant",
        ROOT / "cases/openfoam/single_dof_free_v6_to200/system",
    ]
    checks["case_templates_intact"] = all(path.exists() for path in template_paths)

    report = {
        "schema_version": "post_cleanup_validation_v7",
        "checks": checks,
        "checkpoint_records": checkpoint_records,
        "all_checks_passed": all(checks.values()),
    }
    out = ROOT / "results/cleanup/post_cleanup_validation_v7.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
