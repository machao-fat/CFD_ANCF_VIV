# 预测—校正能量审计定义

## 接口侧

对每个物理步使用实际 CFD 总力 `F=(Fx,Fy,Fz)`，而不是用旧载荷或简单均布替代。分别记录预测界面速度 `v_pred` 和结构校正速度 `v_corr`：

```text
P_CFD       = F · v_pred
P_structure = F_applied · v_corr
P_projection = (F - F_applied) · v_pred
P_temporal   = F_applied · (v_pred - v_corr)
P_defect     = P_projection + P_temporal
W_CFD       = sum(P_CFD dt)
W_structure = sum(P_structure dt)
E_defect    = sum(P_defect dt)
```

`F` 是原始CFD积分力；`F_applied` 是真正送入结构求解器的力。通常二者相同；在 `transverse_only` 诊断中会显式投影掉顺流向分量。这样，总缺陷不会把“人为载荷投影”和“预测—校正时间滞后”混成一个数。`instantaneous_power_W` 仍等于结构实际接收的 `P_structure`。

CSV 每步包含功率、累计功、预测/校正位移速度加速度、`H^T` 映射广义力范数、载荷分量和时间戳。`instantaneous_power_W` 现在明确等于 `P_structure`，不再与 CFD 预测功混用。

## 结构侧

结构储能定义为

```text
E_stored = E_kinetic + E_elastic/geometric + V_base-load
R_E(step) = W_structure(step) - ΔE_stored(step) - W_damping(step)
```

其中 `V_base-load` 是不随时间显式变化的保守基础载荷势能。ANCF 的顶张力通过恒定端部 `base_load` 施加，必须计入 `external_potential_J`；因此在线驱动现在以结构求解器输出的完整 `mechanical_energy_J` 作为 `stored_energy_J`。漏掉这一项会使顶张立管的能量定义不闭合。EB 的顶张力主要进入几何刚度能，但仍保留 `external_potential_energy_J` 字段用于审计。

当前功率积分采用右端点矩形公式，单位链为 `N·m/s=W`、`W·s=J`。载荷CSV必须声明 `force_representation=integrated_N`；若只有 `N/m`，必须先乘切片/单位展向长度，不能直接进入本审计。

离线工具的显式窗口采用状态时刻边界 `(t_start,t_end]`。默认后半段现在只标记为 `heuristic_last_half_not_verified_steady`，不是稳态证明。只有调用者给出对齐的显式窗口、另行验证稳态、初始储能来自真实前一状态且力单位已验证时，`physical_energy_acceptance_ready` 才可能为真。

当前没有求解完整流体总能量方程，因此压力/黏性流体内部耗散不放入结构能量平衡。`W_CFD` 是界面功，不是完整 CFD 能量收支。

## 旧结果重算限制

`results/04_energy_audit/eb_1000_energy.json` 和 `ancf_1000_energy.json` 是对旧 CSV 的重新积分。旧 CSV 没有 `stored_energy_J` 和阻尼功字段，因此 JSON 标记 `explicit_stored_energy=false`，只能说明旧功率列不能直接支撑能量准入；修复后的新 runner 才生成完整字段。

## 自动检查

`src/coupling/online_file_coupling/energy_audit.py` 与 `tests/continuous_handshake/test_energy_audit.py` 检查预测功、结构功、耦合缺陷、初始储能、基础载荷势能、窗口边界及结构平衡的分离；遇到 NaN/Inf、非正时间步或非积分力单位立即失败。
