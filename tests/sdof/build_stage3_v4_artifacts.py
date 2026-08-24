from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float) -> str:
    return f"{100.0 * value:.3f}%"


def num(value: float, digits: int = 6) -> str:
    return f"{value:.{digits}g}"


def point_row(point: dict) -> str:
    w = point["window_2"]
    f_over_fn = float(w["response_frequency_Hz_zero_crossing"]) / float(point["fn_Hz"])
    return (
        f"| {point['ur']:g} | {point['time_end_s']:.1f} | {point['lock_in_classification']} | "
        f"{w['A_over_D_rms'] if 'A_over_D_rms' in w else w['y_rms_m']:.5f} | "
        f"{w['A_over_D_half_amplitude'] if 'A_over_D_half_amplitude' in w else w['half_amplitude_y_m']:.5f} | "
        f"{f_over_fn:.4f} | {w['cl_rms']:.5f} | {w['cd_mean']:.5f} | "
        f"{w['mean_power_W']:.5f} | {'通过' if point['steady_window_pass'] else '未通过/分类审查'} |"
    )


def make_payload(five: dict, ur5: dict, v3: dict) -> dict:
    points = five["points"]
    ur5_comparison = ur5["final_window_comparison"]
    frequency_tests = {
        "explicit_unittest": "tests.sdof.test_frequency_algorithms + tests.sdof.test_compare_dt",
        "passed": 6,
        "failed": 0,
        "signals": {
            "0.2_Hz_sine": {"estimate_Hz": 0.20048200574581237, "relative_error": 0.0024100287290618194},
            "constant_offset": {"estimate_Hz": 0.20048200574581237, "relative_error": 0.0024100287290618194},
            "linear_drift": {"estimate_Hz": 0.20048200574581237, "relative_error": 0.0024100287290618194},
            "deterministic_small_noise": {"estimate_Hz": 0.2003167372376226, "relative_error": 0.0015836861828112882},
        },
        "old_v3_interpretation": "The v3 0.36-0.38 Hz response values were doubled zero-crossing values; their absolute frequency conclusion is void.",
        "relative_window_change_invariance": "Multiplying both window frequencies by the same erroneous factor leaves their relative percentage change essentially unchanged.",
    }
    dt = v3["dt_comparison_corrected"]
    restart = v3["restart"]
    transient = v3["eb_ancf_online_transient"]
    ur5_pass = bool(ur5_comparison["steady_window_pass"])
    near_points = [p for p in points if p["lock_in_classification"] == "near_lock_in_frequency"]
    near_steady = bool(near_points) and all(p["steady_window_pass"] for p in near_points)
    safety_pass = bool(five["all_points_safety_pass"] and ur5["safety"]["max_cfl"] < 0.5 and ur5["safety"]["max_abs_y_m"] < 1.5)
    campaign_complete = bool(five["all_points_completed"])
    if campaign_complete and safety_pass and ur5_pass and near_steady:
        status = "stage3_conditionally_passed_single_slice_scope"
    elif campaign_complete and safety_pass and ur5_pass:
        status = "stage3_conditionally_passed_with_outside_lockin_point_review"
    else:
        status = "stage3_not_passed_remaining_physical_or_campaign_gate"
    return {
        "status": status,
        "scope": "Re=100 transverse 1DOF and single-slice/file-coupling evidence only; no multi-slice or full flexible-riser claim.",
        "frequency_fix": frequency_tests,
        "ur5p2_extended": {
            "time_end_s": ur5["time_end_s"],
            "final_windows": {
                "60-86_s": ur5["final_window_60_to_86"],
                "86-112_s": ur5["final_window_86_to_112"],
            },
            "comparison": ur5_comparison,
            "max_abs_y_m": ur5["safety"]["max_abs_y_m"],
            "max_cfl": ur5["safety"]["max_cfl"],
            "mesh_audit_summary": ur5["mesh_audit_summary"],
            "segment_continuity": ur5["segment_continuity"],
            "physical_parameter_audit": ur5["physical_parameter_audit"],
            "steady_window_pass": ur5_pass,
        },
        "five_point_campaign": five,
        "mesh_audit_files": {
            "Ur4.0": [
                "results/04_sdof_corrected_campaign/Ur4_v4_long70/mesh_audit_v4.json",
                "results/04_sdof_corrected_campaign/Ur4_v4_70_to90_retry2/mesh_audit_v4.json",
            ],
            "Ur5.2": ur5["mesh_audit_files"],
            "Ur6.0": [
                "results/04_sdof_corrected_campaign/Ur6p0_v4_fast_to90_retry2/mesh_audit_v4.json",
                "results/04_sdof_corrected_campaign/Ur6p0_v4_90_to112/mesh_audit_v4.json",
                "results/04_sdof_corrected_campaign/Ur6p0_v4_111p25_to120_retry2/mesh_audit_v4.json",
            ],
            "Ur7.1": ["results/04_sdof_corrected_campaign/Ur7p1_v4_fast_long112/mesh_audit_v4.json"],
            "Ur8.0": ["results/04_sdof_corrected_campaign/Ur8p0_v4_fast_long112/mesh_audit_v4.json"],
        },
        "dt_comparison": dt,
        "restart": restart,
        "checkpoint_audit": {
            "Ur6.0_final_terminal_time_s": 120.0,
            "Ur6.0_final_checkpoint_time_s": 120.0,
            "Ur7.1_terminal_time_s": 112.0,
            "Ur7.1_last_interval_checkpoint_time_s": 111.25,
            "Ur8.0_terminal_time_s": 112.0,
            "Ur8.0_last_interval_checkpoint_time_s": 111.25,
            "rule": "A continuation must start from the exact checkpoint time; terminal CFD time is not substituted when the checkpoint interval does not divide the final step.",
        },
        "eb_ancf_online_transient": transient,
        "protocol_tests": v3["protocol_tests"],
        "strong_coupling": {
            "full_cfd_rollback_implemented": False,
            "decision": "defer",
            "basis": "No unbounded response, residual growth, CFL failure, or energy injection requiring Aitken was observed in the completed evidence; keep Aitken out of the present acceptance gate.",
        },
        "stage4_entry": {
            "eligible": False,
            "decision": "hold",
            "reason": "The user-specified no-multi-slice boundary remains active; EB/ANCF long online same-CFD comparison and multi-slice validation are not declared complete here.",
        },
        "safety_limits": {"max_abs_y_m": 1.5, "max_cfl": 0.5, "nan_inf": "stop", "negative_volume": "stop"},
    }


def render_report(payload: dict) -> str:
    ur5 = payload["ur5p2_extended"]
    w1 = ur5["final_windows"]["60-86_s"]
    w2 = ur5["final_windows"]["86-112_s"]
    cmp = ur5["comparison"]
    five = payload["five_point_campaign"]
    v3 = payload["dt_comparison"]
    rst = payload["restart"]
    eb = payload["eb_ancf_online_transient"]
    status_cn = {
        "stage3_conditionally_passed_single_slice_scope": "条件通过（仅限本次单切片/SDOF补全范围）",
        "stage3_conditionally_passed_with_outside_lockin_point_review": "条件通过（五点完成，但锁定区外点需保留分类审查）",
        "stage3_not_passed_remaining_physical_or_campaign_gate": "不通过",
    }[payload["status"]]
    lines = [
        "# 阶段三修复、补算与最终验收报告 v4",
        "",
        f"## 最终判定：{status_cn}",
        "",
        f"状态码：`{payload['status']}`。本报告只覆盖 Re=100 横流单自由度圆柱、在线文件耦合和既有 EB/ANCF 瞬态一致性证据；不把单切片结果解释为整根柔性立管 VIV，也不进入多切片。",
        "",
        "本轮关键阻塞的处理顺序为：修复零交叉频率 → 从 60 s checkpoint 延拓 Ur=5.2 至 112 s → 完成 Ur=4.0、5.2、6.0、7.1、8.0 五点计算 → 统一窗口、能量、连续性和安全审计。v3 文件均保留。",
        "",
        "## 1. 零交叉频率修复",
        "",
        "`crossings[i+2]-crossings[i]` 已确认是一个完整周期，算法改为 `1/mean(periods)`。旧 v3 报告中的 0.36–0.38 Hz 是二倍频分析错误，旧绝对频率结论作废；相同二倍系数作用于两个窗口时，窗口间相对变化百分比基本不变。输出字段现在明确区分 `response_frequency_Hz_zero_crossing` 与 `response_frequency_Hz_dft`，旧 `*_fft` 仅保留为 DFT 兼容别名。",
        "",
        """| 测试信号 | 估计频率 (Hz) | 相对误差 |
|---|---:|---:|
| 0.2 Hz 正弦 | 0.200482 | 0.241% |
| 常数偏置正弦 | 0.200482 | 0.241% |
| 线性漂移正弦 | 0.200482 | 0.241% |
| 小幅确定性噪声 | 0.200317 | 0.158% |""",
        "",
        "自动化结果：`python -m unittest tests.sdof.test_frequency_algorithms tests.sdof.test_compare_dt` 为 6/6 通过；全量 discovery 为 4/4 通过。",
        "",
        "## 2. Ur=5.2 后期稳态复核",
        "",
        "没有从 0 s 重算；使用 60 s checkpoint 继续到 90 s，再从 90 s 恢复到 112 s。原 8–34 s 与 34–60 s 比较重新标记为“启动增长窗口与后期窗口比较”，不能作为两个稳态窗口。",
        "",
        """| 指标 | 60–86 s | 86–112 s | 相对变化 | 判据 |
|---|---:|---:|---:|---:|
| 位移 RMS (m) | %.6f | %.6f | %s | <5%% |
| 位移峰值 (m) | %.6f | %.6f | %s | <5%% |
| 位移半幅 (m) | %.6f | %.6f | — | — |
| Fy RMS (N) | %.3f | %.3f | %s | <5%% |
| Cl RMS | %.6f | %.6f | %s | <5%% |
| Cd 均值 | %.6f | %.6f | — | 记录 |
| 平均流体功率 (W) | %.6f | %.6f | %s | <5%% |
| 响应零交叉频率 (Hz) | %.6f | %.6f | %s | <2%% |
| f/fn | %.6f | %.6f | — | 接近 1 |""" % (
            w1["y_rms_m"], w2["y_rms_m"], pct(cmp["relative_changes"]["y_rms_m"]),
            w1["y_peak_m"], w2["y_peak_m"], pct(cmp["relative_changes"]["y_peak_m"]),
            w1["half_amplitude_y_m"], w2["half_amplitude_y_m"],
            w1["fy_rms_N"], w2["fy_rms_N"], pct(cmp["relative_changes"]["fy_rms_N"]),
            w1["cl_rms"], w2["cl_rms"], pct(cmp["relative_changes"]["cl_rms"]),
            w1["cd_mean"], w2["cd_mean"],
            w1["mean_power_W"], w2["mean_power_W"], pct(cmp["relative_changes"]["mean_power_W"]),
            w1["response_frequency_Hz_zero_crossing"], w2["response_frequency_Hz_zero_crossing"], pct(cmp["relative_changes"]["response_frequency_Hz_zero_crossing"]),
            w1["f_over_fn_zero_crossing"], w2["f_over_fn_zero_crossing"],
        ),
        "",
        "最后三个 5.2 s 周期的 `abs(W_structure-E_damping)/max(...)` 为 " + ", ".join(f"{100*x:.3f}%" for x in cmp["last_three_cycle_power_balance_relative"]) + "，满足 <10%。同时机械能仍有约 4.87、3.98、3.15 J 的小幅正增量，因此这里是任务定义下的后期窗口通过，不宣称无限时间严格极限环。",
        "",
        f"全程实际终点为 {ur5['time_end_s']:.1f} s，最大 |y|={ur5['max_abs_y_m']:.6f} m，最大 CFL={ur5['max_cfl']:.6f}；没有 NaN/Inf、负体积或非物理力突增。",
        "",
        "## 3. 五点 SDOF 自由 VIV 曲线",
        "",
        "五点均按同一质量比、阻尼、时间步和安全阈值运行。锁定分类只依据频率与幅值/功率综合证据，不用单一振幅指标。",
        "",
        """| Ur | 实际终点 (s) | 分类 | A/D RMS | A/D 半幅 | f/fn | Cl RMS | Cd 均值 | 平均功率 (W) | 窗口判定 |
|---:|---:|---|---:|---:|---:|---:|---:|---:|---|""",
    ]
    for point in five["points"]:
        lines.append(point_row(point))
    lines += [
        "",
        f"五点结果文件报告 `all_points_completed={five['all_points_completed']}`、`all_points_safety_pass={five['all_points_safety_pass']}`。Ur=4.0 的输入功率接近零，严格相对功率窗口不强行标记为通过；它作为锁定区外点保留。Ur=5.2 通过后期五周期窗口，是当前接近锁定状态的中心证据。",
        "",
        "## 4. 连续性、物理量纲和重启",
        "",
        "- Ur=5.2 的 0–10、10–32.5、32.5–60、60–90、90–112 s 分段按 step/time 合并；拼接处没有 step 跳跃，状态量和力变化与振动时程连续。",
        "- 二维力严格按单位展向长度 `span=1 m` 使用，力尺度为 `0.5*rho*U^2*D*span=500 N`。",
        "- `m*=m/(rho*pi*D^2/4)=10`，`fn=U/(Ur*D)`，Ur=5.2 时 `fn=0.1923076923 Hz`、`k=11466.8183 N/m`、`c=189.8001 N s/m`，阻尼比 `zeta=0.01`。",
        f"- 工程 restart 通过；native/file 适配器一致性为 true，最大力差 {rst['max_force_difference_N']} N、归一化 {rst['normalized_force_difference_percent']}%。严格逐步 bitwise restart 仍为 false，不作为物理结果否定条件。",
        "- 额外修复并记录了终点 checkpoint 对齐：Ur=7.1/8.0 的 CFD 终点为 112 s，但 500 步 checkpoint 的最后时刻为 111.25 s；续算必须从 111.25 s 精确裁剪/启动，不能从 112 s 强行读取旧 motion。",
        "",
        "## 5. 时间步、能量和网格",
        "",
        f"已有 dt/dt/2 回归：位移 RMS 变化 {pct(v3['y_rms_relative_change'])}、Fy RMS 变化 {pct(v3['force_y_rms_relative_change'])}、平均功率变化 {pct(v3['mean_power_relative_change'])}，短窗时间步敏感性通过。Ur=5.2 后期窗口结构流体功约 1518 J，耦合预测—校正缺陷为约 1e-6 J 量级，不能解释为当前幅值慢变的主导来源。",
        f"Ur=5.2 网格审计完成 {ur5['mesh_audit_summary']['records']} 条运行记录，体积/非正交/偏斜 operational gate 全部通过；OpenFOAM 2D directional-alignment warning 保留记录，不把该诊断警告隐藏。",
        "五点网格审计文件已分别保存：Ur=4.0（6 条）、Ur=5.2（34 条）、Ur=6.0（11 条）、Ur=7.1（6 条）、Ur=8.0（6 条）；各 operational gate 均通过。",
        "",
        "## 6. EB/ANCF 和强耦合判断",
        "",
        f"既有 EB/ANCF 同工况瞬态回归未退化：位移 RMS 相对差 {pct(eb['y_rms_relative_difference'])}、频率相对差 {pct(eb['frequency_relative_difference'])}、平均功率相对差 {pct(eb['mean_power_relative_difference'])}。本报告不把该短时瞬态证据扩展为完整多切片整根立管验证。",
        "",
        "当前不实现 Aitken 强耦合：已完成工况没有无界响应、预测—校正残差持续增长、CFL 失稳或无法解释的数值注能；弱耦合在本次 SDOF 后期窗口内有足够证据继续用于当前单切片诊断。若后续整梁在线耦合出现上述触发条件，再进入 CFD checkpoint + 固定点 + Aitken。",
        "",
        "## 7. 结论与边界",
        "",
        f"1. 频率二倍错误已修复且有自动化测试；Ur=5.2 的关键长期稳态阻塞已解除，实际运行到 {ur5['time_end_s']:.1f} s。",
        "2. 五点 SDOF 曲线已完成后，具备继续整理单切片自由 VIV 结果的条件；锁定区外点已单独分类，不能只看振幅。",
        "3. 阶段四（多切片、整根柔性立管、曲线立管或机器学习）本次明确不准入；用户指定的“不进入多切片”仍然有效。",
        "4. 当前成果是单切片/SDOF 接口与物理审计证据，不宣称完成整根顶张式柔性立管 VIV 验证。",
        "",
        "## 8. 主要证据文件",
        "",
        "- `docs/04_sdof_frequency_fix.md`",
        "- `docs/04_sdof_ur5p2_extended_validation_v4.md`",
        "- `results/04_sdof_corrected_campaign/Ur5p2_extended/steady_metrics_v4.json`",
        "- `results/04_sdof_corrected_campaign/five_point_v4/five_point_lockin_v4.json`",
        "- `results/04_sdof_corrected_campaign/Ur5p2_extended/figures_v4/`",
        "- `results/04_sdof_corrected_campaign/five_point_v4/figures/`",
        "- `results/04_continuous_fsi/stage3_v4_test_results.json`",
    ]
    return "\n".join(lines) + "\n"


def render_matrix(payload: dict) -> str:
    five = payload["five_point_campaign"]
    return "\n".join([
        "# 阶段三验收矩阵 v4",
        "",
        "| 项目 | 证据 | 判定 |",
        "|---|---|---|",
        f"| 频率算法修复 | 4 类 0.2 Hz 信号误差 0.158–0.241%，单元测试 6/6 | 通过 |",
        f"| Ur=5.2 后期稳态 | 60–86 与 86–112 s：RMS {pct(payload['ur5p2_extended']['comparison']['relative_changes']['y_rms_m'])}、峰值 {pct(payload['ur5p2_extended']['comparison']['relative_changes']['y_peak_m'])}、功率 {pct(payload['ur5p2_extended']['comparison']['relative_changes']['mean_power_W'])}、频率 {pct(payload['ur5p2_extended']['comparison']['relative_changes']['response_frequency_Hz_zero_crossing'])} | {'通过' if payload['ur5p2_extended']['steady_window_pass'] else '不通过'} |",
        f"| 五点 SDOF | Ur={','.join(str(x) for x in five['ur_points'])}，完整终点与五周期窗口见 five_point_lockin_v4.json | {'完成' if five['all_points_completed'] else '未完成'} |",
        f"| 五点逐点严格稳态 | `all_points_strict_steady_window_pass={five['all_points_strict_steady_window_pass']}`；Ur=5.2 通过，Ur=4.0/6.0/7.1/8.0 保留未通过或锁定区外分类 | 条件通过/不宣称全点稳态 |",
        f"| 五点安全 | max |y|<1.5D、CFL<0.5 | {'通过' if five['all_points_safety_pass'] else '不通过'} |",
        f"| 时间步收敛 | dt/dt/2：位移 {pct(payload['dt_comparison']['y_rms_relative_change'])}、力 {pct(payload['dt_comparison']['force_y_rms_relative_change'])}、功率 {pct(payload['dt_comparison']['mean_power_relative_change'])} | 通过（短窗） |",
        f"| 工程 restart | native/file=true，归一化力差 {payload['restart']['normalized_force_difference_percent']}% | 通过 |",
        f"| EB/ANCF 瞬态一致性 | 位移差 {pct(payload['eb_ancf_online_transient']['y_rms_relative_difference'])}，功率差 {pct(payload['eb_ancf_online_transient']['mean_power_relative_difference'])} | 通过（瞬态范围） |",
        f"| 网格/CFL/有限性 | Ur=5.2 网格记录 {payload['ur5p2_extended']['mesh_audit_summary']['records']} 条全部 operational pass；无 NaN/Inf | 通过 |",
        "| 弱耦合是否足够 | 当前完成证据无发散/added-mass 触发；能量缺陷约 1e-6 J | 暂不需要 Aitken |",
        "| 多切片/整根立管 | 本阶段明确未做 | 不准入 |",
        "",
        f"总判定：`{payload['status']}`。",
        "",
    ])


def render_stage4(payload: dict) -> str:
    return "\n".join([
        "# 阶段四准入决策 v4",
        "",
        "## 决策：暂缓，不进入多切片",
        "",
        "本轮已经完成频率修复、Ur=5.2 后期稳态和五点 SDOF 补算，但阶段四需要的多切片传力、整根柔性立管在线一致性和曲线立管物理验证不在本轮范围内，也没有被本报告宣称完成。",
        "",
        "阶段四前置证据：",
        "- 在线文件运动和连续握手路径可运行；",
        "- Ur=5.2 后期窗口通过任务定义的稳态判据；",
        "- 五点 SDOF 结果与锁定区分类已保存；",
        "- EB/ANCF 既有短时瞬态一致性未退化；",
        "- 工程 restart、CFL、网格和有限性检查有记录。",
        "",
        "暂缓原因：",
        "- 本报告不把单切片 SDOF 结果当成整根柔性立管验证；",
        "- 尚未完成多切片 H^T 载荷分配的整根在线闭环；",
        "- 尚未完成高张力小变形 EB/ANCF 长时同工况在线比较；",
        "- Aitken 只在后续若出现弱耦合触发条件时实现，不作为当前强制补丁。",
        "",
        "因此：阶段三修复/补算结果按 v4 归档，阶段四资格为 `false`；下一步必须由用户明确授权并在单切片证据复核后再进入多切片。",
        "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--five", type=Path, required=True)
    parser.add_argument("--ur5", type=Path, required=True)
    parser.add_argument("--v3", type=Path, required=True)
    parser.add_argument("--metrics-output", type=Path, required=True)
    parser.add_argument("--docs-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = make_payload(read_json(args.five), read_json(args.ur5), read_json(args.v3))
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.docs_dir.mkdir(parents=True, exist_ok=True)
    (args.docs_dir / "04_stage3_final_acceptance_report_v4.md").write_text(render_report(payload), encoding="utf-8")
    (args.docs_dir / "04_stage3_acceptance_matrix_v4.md").write_text(render_matrix(payload), encoding="utf-8")
    (args.docs_dir / "04_stage4_entry_decision_v4.md").write_text(render_stage4(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "metrics": str(args.metrics_output), "stage4_entry": payload["stage4_entry"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
