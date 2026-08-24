"""Build v5 reports and machine-readable acceptance decisions from v5 evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--ur5-sensitivity", type=Path, required=True)
    parser.add_argument("--eb-ancf", type=Path, required=True)
    parser.add_argument("--matlab", type=Path, required=True)
    parser.add_argument("--python-tests", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.output_root.resolve()
    docs = root / "docs"
    results = root / "results" / "04_continuous_fsi"
    summary = load(args.summary)
    sensitivity = load(args.ur5_sensitivity)
    eb_ancf = load(args.eb_ancf)
    matlab = load(args.matlab)
    python_tests = load(args.python_tests)
    points = summary["points"]
    blockers = []
    if sensitivity["status"] != "robust_window_pass":
        blockers.append("Ur=5.2窗口平移敏感性仅最后一组通过，属于边界通过")
    if not summary.get("all_points_strict_steady_window_pass", False):
        blockers.append("五点中仍有至少一个工况未达到统一严格稳态或低能量绝对判据")
    if not summary.get("all_points_safety_pass", False):
        blockers.append("五点安全审计未全部通过")
    if not eb_ancf.get("comparison", {}).get("acceptance", {}).get("physical_acceptance_ready", False):
        blockers.append("EB/ANCF长时在线比较未同时满足两组五周期窗口和物理幅值验收")
    if int(python_tests.get("failed", 0)) != 0:
        blockers.append("Python全量测试存在失败")
    if int(matlab.get("failed", 0)) != 0:
        blockers.append("MATLAB回归存在失败")
    stage3_fully_passed = len(blockers) == 0
    stage3_conditionally_passed = bool(summary.get("all_points_completed", False) and summary.get("all_points_safety_pass", False) and int(python_tests.get("failed", 0)) == 0 and int(matlab.get("failed", 0)) == 0)
    eligible = stage3_fully_passed
    point_lines = []
    for p in points:
        point_lines.append(
            f"| {p['ur']} | {p.get('time_end_s')} | {p.get('final_steady_window_pass')} | {p.get('frequency_state')} | {p.get('physical_lockin_classification')} | {p.get('max_cfl')} | {p.get('max_abs_y_m')} |"
        )
    metrics = {
        "status": "stage3_fully_passed" if stage3_fully_passed else "stage3_conditionally_passed" if stage3_conditionally_passed else "stage3_not_passed",
        "stage3_conditionally_passed": stage3_conditionally_passed,
        "stage3_fully_passed": stage3_fully_passed,
        "remaining_blockers": blockers,
        "eligible_for_stage4_prototype": eligible,
        "stage4_scope": "If eligible, only minimal two/three-slice prototype; no full-riser validation claim.",
        "frequency_method": "response and lift DFT primary; corrected zero crossing diagnostic; multi-harmonic test required",
        "ur5p2_window_sensitivity": sensitivity,
        "five_point": summary,
        "eb_ancf_long_time_online": eb_ancf,
        "python_tests": python_tests,
        "matlab_tests": matlab,
        "safety_limits": {"max_abs_y_m": 1.5, "max_cfl": 0.5, "nan_inf": "stop", "negative_volume": "stop"},
        "scope_boundary": "No multi-slice or full flexible-riser physical validation is claimed.",
    }
    results.mkdir(parents=True, exist_ok=True)
    (results / "stage3_final_metrics_v5.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=True) + "\n", encoding="utf-8")
    (results / "stage3_v5_test_results.json").write_text(json.dumps({"python": python_tests, "matlab": matlab, "discovery_note": "Python recursive discovery was repaired by package markers; only tests executed in this run are counted."}, indent=2, ensure_ascii=False, allow_nan=True) + "\n", encoding="utf-8")

    write(docs / "04_stage3_completion_plan_v5.md", f"""# 阶段三补全执行记录 v5

本轮按 checkpoint 续算和实际回归证据推进，保留全部 v4 文件，不进入多切片。

## 执行顺序

1. 修正 DFT/零交叉频率职责，增加多谐波测试。
2. 修复 Python `unittest discover` 包发现机制。
3. 对 Ur=5.2 做三组窗口平移复核，不从 0 s 重算。
4. 对其余四点从物理一致 checkpoint 延拓，并逐点重新分析。
5. 运行独立 EB/ANCF 在线长时比较，记录结构模型差异与 CFD 反馈差异。
6. 汇总图表、Python/MATLAB 测试和阶段准入矩阵。

本轮最终布尔值：`stage3_fully_passed={str(stage3_fully_passed).lower()}`，`eligible_for_stage4_prototype={str(eligible).lower()}`。
""")
    write(docs / "04_sdof_five_point_steady_validation_v5.md", f"""# 五点 SDOF 稳态复核 v5

## 统一判据

常规点使用 RMS、峰值/半幅值、Fy RMS、Cl RMS、DFT 主频和平均输入功率窗口变化阈值 5%，频率阈值 2%，最后三个周期能量不平衡阈值 10%。当两窗平均功率绝对值均小于 0.5 W 时，额外检查无持续机械能增长、幅值/力稳定和周期机械能变化；低功率不自动等于稳态。

## 五点结果

| Ur | 最终时间(s) | 严格稳态 | 频率状态 | 物理分类 | 最大CFL | 最大位移(m) |
|---:|---:|---|---|---|---:|---:|
{chr(10).join(point_lines)}

Ur=5.2 的三组窗口平移结果见 `{args.ur5_sensitivity.resolve()}`。本轮窗口状态为 `{sensitivity['status']}`，通过组合数为 {sensitivity['passed_combinations']}/3；因此不能将其表述为窗口起点不敏感的稳健稳态。

五点曲线使用实心点表示严格稳态，空心点表示已计算但未严格稳态，星号表示低功率绝对判据通过；未稳态点不参与物理锁定曲线连线。
""")
    write(docs / "04_lockin_classification_method_v5.md", """# 锁定/同步分类方法 v5

一级状态是频率同步：`0.95 <= f_response/fn <= 1.05` 为 `frequency_synchronized`，否则为 `outside_frequency_sync`；当窗口未稳态或 DFT/零交叉差异超过 5% 时为 `frequency_unresolved`。

二级物理分类只有在严格稳态或明确通过低功率绝对判据后才启用：`locked_or_near_lockin` 还要求同步、正的非噪声流体输入功率和力—速度相位方向一致；`outside_lockin` 要求稳态但不同步或保持低响应；其余统一归为 `transitional_or_unsteady`。频率同步不再单独称作锁定。
""")
    write(docs / "04_lift_frequency_method_v5.md", """# 升力主频提取方法 v5

位移和升力均计算去趋势 DFT 与修正零交叉频率。位移频率以 DFT 为主，零交叉用于一致性诊断；升力频率固定使用去趋势 DFT 谱峰，零交叉只输出 `lift_zero_crossing_reliable` 和 `lift_dft_zero_crossing_relative_difference`，不得覆盖 DFT 结果。多谐波测试 `sin(2πft)+0.4sin(4πft)` 验证基频识别。
""")
    eb_acc = eb_ancf.get("comparison", {}).get("acceptance", {})
    write(docs / "04_eb_ancf_long_time_online_comparison_v5.md", f"""# EB/ANCF 长时在线比较 v5

比较使用独立 CFD 进程、同一初始流场、同一网格、同一质量/阻尼/张力/时间步和同一横流载荷投影。结果分别报告结构模型差异和运动反馈造成的 CFD 力差异。

- 实际共同结束时间：{eb_ancf.get('time_end_s')} s。
- EB/ANCF 同网格：{eb_ancf.get('same_mesh')}。
- 物理幅值可辨识：{eb_acc.get('physical_amplitude_identifiable')}。
- 两个相邻五周期窗口：{eb_acc.get('two_adjacent_late_windows_available')}；每窗五个有效结构周期：{eb_acc.get('five_effective_structural_cycles_per_window')}。
- 结构模型 RMS、峰值、主频和功率差分别为：{eb_ancf.get('comparison', {}).get('structure_model_difference')}。
- CFD 反馈力差异单列为：{eb_ancf.get('comparison', {}).get('independent_cfd_feedback_difference')}。

该比较不构成多切片或整根立管验证。
""")
    write(docs / "04_stage3_final_acceptance_report_v5.md", f"""# 阶段三最终验收报告 v5

## 最终结论

`stage3_conditionally_passed={str(stage3_conditionally_passed).lower()}` ；`stage3_fully_passed={str(stage3_fully_passed).lower()}`。

阶段三正式全部通过要求的所有条件尚未被自动放宽。当前阻塞项为：

{chr(10).join('- ' + b for b in blockers) if blockers else '- 无'}

## 证据摘要

- Python 全量 discovery：{python_tests.get('passed')} passed / {python_tests.get('failed')} failed / {python_tests.get('total')} total，且明确是本轮执行。
- MATLAB 回归：{matlab.get('passed')} passed / {matlab.get('failed')} failed / {matlab.get('total')} total，且明确是本轮执行。
- 五点均完成实际运行或 checkpoint 延拓：{summary.get('all_points_completed')}；安全审计：{summary.get('all_points_safety_pass')}。
- Ur=5.2 窗口敏感性：{sensitivity.get('status')}，{sensitivity.get('passed_combinations')}/3 组通过。
- EB/ANCF 长时在线物理比较：{eb_ancf.get('status')}。

旧 v3 报告中的零交叉频率二倍错误及其绝对频率结论已由 v4 记录作废；v5 所有物理分类使用 DFT 主频和两级状态。

## 范围边界

本报告不宣称完成多切片、整根柔性立管或工程 VIV 验证。Aitken/rollback 仍按证据门控，不作为无必要的强制项。
""")
    matrix_rows = []
    gates = [
        ("频率算法及多谐波测试", int(python_tests.get('failed', 1)) == 0, "Python full discovery"),
        ("Ur=5.2窗口平移敏感性", sensitivity.get('status') == 'robust_window_pass', str(sensitivity.get('status'))),
        ("五点可信最终状态", summary.get('all_points_strict_steady_window_pass', False), str(summary.get('status'))),
        ("EB/ANCF长时在线比较", eb_acc.get('physical_acceptance_ready', False), str(eb_ancf.get('status'))),
        ("Python全量测试", int(python_tests.get('failed', 1)) == 0, f"{python_tests.get('passed')}/{python_tests.get('total')}"),
        ("MATLAB回归", int(matlab.get('failed', 1)) == 0, f"{matlab.get('passed')}/{matlab.get('total')}"),
        ("无多切片越界宣称", True, "scope boundary retained"),
    ]
    for gate, passed, evidence in gates:
        matrix_rows.append(f"| {gate} | {'PASS' if passed else 'BLOCKED'} | {evidence} |")
    write(docs / "04_stage3_acceptance_matrix_v5.md", f"""# 阶段三验收矩阵 v5

| 验收项 | 状态 | 本轮证据 |
|---|---|---|
{chr(10).join(matrix_rows)}

`stage3_fully_passed={str(stage3_fully_passed).lower()}`。阻塞项必须解决后才能改变结论，不得通过降低阈值、修改物理参数或截取局部窗口规避。
""")
    write(docs / "04_stage4_entry_decision_v5.md", f"""# 阶段四准入决定 v5

`eligible_for_stage4_prototype={str(eligible).lower()}`。

阶段四前置条件只来自阶段三成果：规定运动 CFD、文件式在线交换、工程 restart、时间步/网格/CFL/能量审计、五点 SDOF 状态、Ur=5.2 基准、EB/ANCF 长时单切片比较和全量自动测试。本轮尚有以下阻塞，因此暂不准入：

{chr(10).join('- ' + b for b in blockers) if blockers else '- 前置条件全部满足'}

多切片 H^T 分配和整根在线闭环属于阶段四工作内容，不作为循环前置条件；即使未来准入，也仅允许先做最小双切片/三切片原型，不等于整根立管验证完成。
""")
    print(json.dumps({"stage3_fully_passed": stage3_fully_passed, "stage3_conditionally_passed": stage3_conditionally_passed, "eligible_for_stage4_prototype": eligible, "blockers": blockers}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
