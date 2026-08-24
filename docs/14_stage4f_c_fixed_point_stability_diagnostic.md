# Stage 4F-C 单物理步固定点稳定性诊断

## 结论

固定点稳定性诊断通过，但 Stage 4F-C 生产 Gate 仍不得通过。

`FIXED_POINT_STABILITY_DIAGNOSTIC: passed`

`STAGE4F_C_PRODUCTION_GATE: do_not_pass`

## 根因

原显式弱耦合事务用上一载荷从 committed 状态生成 predictor，并在 predictor 几何上推进 CFD；随后用新 CFD 载荷从同一个 committed 状态生成 corrector，最终提交 corrector 结构状态，但 CFD 场和网格仍对应 predictor。下一步开始时，网格在零物理时间内从 predictor 对齐到 corrector，形成交替网格速度冲击。

D1/D2 中 `Cd` 和 predictor/corrector 速度差每次交互约放大 2.5 倍；时间步减半只增加单位物理时间内的交互次数，没有形成时间步收敛。

## 真实固定点诊断

所有迭代均从同一个父 checkpoint 回滚，只计算 `1.5075 -> 1.508125 s` 这一个物理步。耦合迭代没有作为额外物理时间提交。

- `alpha=0.25`：残差 `0.99571 -> 0.71642 -> 0.49871 -> 0.33857`，连续收缩。
- `alpha=0.50`：残差 `0.99571 -> 0.36106 -> 0.11156 -> 0.03257`，连续收缩。
- `alpha=0.50` 最终 `max|Cd|=6.85675`。
- `alpha=0.50` 最终 predictor/corrector 速度差 `7.9367e-5 U`。
- 所有诊断 solver 日志通过，力转换误差为0，虚功误差保持约机器精度。

该结果只证明单步界面映射可通过常数松弛收缩，不构成生产强耦合、restart、短窗 A/B/C 或 VIV 验收。

## 下一授权

必须明确选择新的数值耦合合同：

1. 一阶显式滞后：提交 predictor，使结构与 CFD checkpoint 几何一致，新载荷只用于下一物理步；或
2. 分区强耦合：每个物理步允许固定点迭代，并冻结常数松弛、残差、最大迭代数、回滚和统一 checkpoint 规则。

这两种选择都会改变现行 `coupling_iteration=0` 的事务，不能作为普通修复暗中实施。

