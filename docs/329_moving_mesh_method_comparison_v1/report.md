# Stage329 动网格方法 smoke 对比

本阶段在相同三切片、8 步、`dt=0.005 s` 和 `optimized_audited` 配置下比较 OpenFOAM 10 原生动网格方法。旧 runtime 和物理设置均未修改。

| 方法 | 墙钟 (s) | 相对 uniform | Gate | 结论 |
|---|---:|---:|---|---|
| uniform | 81.299 | 1.00x | pass | 基线 |
| inverseDistance | 21.139 | 3.85x | pass | 首选 |
| quadratic | 22.042 | 3.69x | pass | 备选 |
| exponential | 40.296 | 2.02x | pass | 可用但较慢 |
| displacementSBRStress | - | - | do_not_pass | 两种线性求解配置均出现 `sigFpe` |
| RBF（Wendland C2，OpenFOAM 10 自定义移植） | 23.016 (Stage330) / 23.294 (Stage333) | 3.48x / 3.49x（仅墙钟，不代表有效结果） | do_not_pass | preCICE 位移场虽按 slice 区分，但流体 `U/p/meshPhi/Force` 在三个 slice 完全相同；RBF solver 未读取当前步的有效边界位移，不能进入生产配置 |

`inverseDistance` 和 `quadratic` 的 8-step smoke 均完成 8/8 结构提交、三个 fluid `End`、网格 hash 变化、preCICE identity 校验和 `owned_residual=0`。与 uniform 比较时，最大相对合力差分别约为 0.323% 和 1.024%，接口位移差均在 smoke 量级内；这不是正式数值等价性证明，长时间使用前仍需独立资格验证。

推荐将 `inverseDistance 1(cyl)` 作为下一阶段候选；保留 `quadratic inverseDistance 1(cyl)` 作为网格质量备选。RBF 已完成 OpenFOAM 10 自定义移植和两次独立 smoke（Stage330、Stage333），但均因 slice force identity 失败而 fail-closed。Stage333 修复了面值/点值索引越界并使用最近面映射；问题仍表现为 solver 调用时边界值为零，说明需后续按 preCICE adapter 的数据更新生命周期重新接入，当前不进入生产配置。

Gate：`STAGE4F_D_MOVING_MESH_METHOD_COMPARISON_V1_GATE: pass_with_rejected_candidates`
