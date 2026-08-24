import json
from pathlib import Path

P = Path(__file__).resolve().parents[3] / "results" / "08_stage4e_physical_baseline_v3_2"
a = json.loads((P / "ancf_modal_state_export_audit.json").read_text(encoding="utf-8"))
c = json.loads((P / "old_new_modal_crosscheck.json").read_text(encoding="utf-8"))
h = json.loads((P / "formal_H_projection_with_qmode.json").read_text(encoding="utf-8"))
s = json.loads((P / "seven_nine_slice_candidates.json").read_text(encoding="utf-8"))
u = json.loads((P / "seven_nine_uncertainty.json").read_text(encoding="utf-8"))
print("modal", [(k, v["qmode_shape"], v["max_mass_orthogonality_error"], v["max_eigen_residual_relative"], v["max_abs_fixed_qmode"]) for k, v in a["per_nElem"].items()])
print("cross", [(k, v["max_frequency_relative_error_first8"], min(v["single_mode_MAC_first8"]), {x: y["subspace_MAC_min"] for x, y in v["target_subspace_crosscheck"].items()}) for k, v in c["per_nElem"].items()])
for grid in h["per_grid"]:
    print("H", grid, [(x, h["per_grid"][grid][x]["procrustes_relative_error"], h["per_grid"][grid][x]["subspace"]["subspace_MAC_min"], h["per_grid"][grid][x]["max_slice_relative_error_physical_scaled"]) for x in ["CF_mode_1", "IL_mode_2", "IL_mode_4"]])
print("candidates")
for k, v in s["candidates"].items():
    print(k, v["nominal_pass"], v["global_relative_errors"], v["modal_normalized_absolute_error_max"], v["direction_classification"])
print("unc")
for method, d in u["per_method"].items():
    for k, v in d.items():
        print(method, k, v["max_global_error_p95"], v["max_modal_error_p95"], v["direction_changes"], v["inactive_buffer_coverage_all_samples"], v["robust_pass"])
