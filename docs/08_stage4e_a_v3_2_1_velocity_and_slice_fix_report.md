# Stage 4E-A-v3.2.1：速度量纲与 7/9 切片修正报告

状态：完成离线 Python 修正；未启动 MATLAB、OpenFOAM 或真实 CFD。

## 速度量纲

冻结公式为 `U_global_mps = 0.48 * U_digitized_mmps / 1365`。因此每 mm/s 的固定缩放为 `0.00035164835164835164 m/s`，相对于旧的 `U_digitized/1000` 结果，修正比例为 `0.48/1.365 = 0.3516483516483516`。数字化名义值 1365 mm/s 精确映射到 0.48 m/s，正负符号保持不变；切片中心速度均满足 `abs(U_i) <= 0.48 m/s`。

每个候选中心的 `s/L`、`s_ref_m`、`slice_length_m`、`U_global_mps`、`flow_sign`、`active` 与 `local_Reynolds` 已写入 [corrected_velocity_profile.json](../results/08_stage4e_physical_baseline_v3_2_1/corrected_velocity_profile.json)。Reynolds 数仅作后续真实 CFD 设计诊断。

## 切片候选

重新计算了均匀 7、均匀 9、零交叉感知 7 和零交叉感知 9，并分别保留线性与 PCHIP 的四类全局积分、m=1/2/4 模态加权载荷误差、方向、零交叉和单次 `slice_length_m` 权重审计。每个方案严格无间隙、无重叠、覆盖 `[0,L]`，切片长度为正，中心严格位于边界内部。

名义上四个方案均通过；但冻结稳健性必须同时满足线性和 PCHIP 的 p95 阈值。均匀 9 与零交叉感知 9 满足全局 p95 ≤5%、模态 p95 ≤10%、方向变化次数为 0。零交叉感知 7 的 PCHIP 模态 p95 为约 10.42%，因此不能作为最终冻结方案。

推荐：`zero_crossing_aware_9_point_sampling`。完整独立证据见 [corrected_seven_nine_slice_candidates.json](../results/08_stage4e_physical_baseline_v3_2_1/corrected_seven_nine_slice_candidates.json) 与 [corrected_profile_uncertainty.json](../results/08_stage4e_physical_baseline_v3_2_1/corrected_profile_uncertainty.json)。
