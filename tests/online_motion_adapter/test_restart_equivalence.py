from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_restart_equivalence import compare_force_series  # noqa: E402


def _write_forces(case: Path, start: str, values: list[tuple[float, float, float]]) -> None:
    path = case/"postProcessing"/"cylinderForces"/start/"forces.dat"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# synthetic"]
    for time_s, fx, fy in values:
        lines.append(f"{time_s} (({fx} {fy} 0) (0 0 0)) ((0 0 0) (0 0 0))")
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")


def test_restart_force_merge_preserves_step_sequence_and_boundary_duplicate():
    with tempfile.TemporaryDirectory() as raw:
        tmp_path = Path(raw)
        reference = tmp_path/"reference"
        restarted = tmp_path/"restarted"
        _write_forces(reference, "0", [(0.0, 1.0, 2.0), (0.1, 1.1, 2.1), (0.2, 1.2, 2.2)])
        _write_forces(restarted, "0", [(0.0, 1.0, 2.0), (0.1, 1.1, 2.1)])
        _write_forces(restarted, "0.1", [(0.1, 1.1, 2.1), (0.2, 1.2, 2.2)])
        result = compare_force_series(reference, restarted, restart_time_s=0.1)
        assert result["time_sequence_exact"] is True
        assert result["common_samples"] == 3
        assert len(result["restart_boundary_duplicates"]) == 1
        assert result["max_restart_boundary_duplicate_difference_N"] == 0.0
        assert result["force_rmse_N"]["y"] == 0.0
