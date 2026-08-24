# 张力与结构残差审计

## 定义

- EB：没有轴向动态自由度。`T0(s)` 是冻结的参考/总张力剖面，`dynamic_increment=0`；不能把几何刚度项误报为动态轴向力。
- ANCF：`tension_N = EA * Green_strain * ||r_s||`，单位为 N；参考张力取初始化所用 `topTension_N`，同时输出总张力最小/最大值和相对参考值的动态增量。
- `compression_risk` 在总张力小于 `-1e-10*max(1,T_reference)` 时置真；不以调低 Newton 容差掩盖负轴力。

## 残差

ANCF 记录 Newton 首次残差、最终残差、残差尺度、绝对/相对残差、相对容差和迭代次数。相对残差定义为

```text
r_rel = ||R||_inf / max(1, ||Q_ext||_inf)
```

EB 也采用同一尺度输出线性 Newmark 平衡残差，便于两分支比较。预测器只使用状态副本，校正器才推进持久状态。

## 回归结果

`tests/structure_runners/test_structure_runner_contract.m` 已通过 EB/ANCF 两分支：20 步、predictor 不覆盖持久状态、checkpoint 读回、张力有限性、参考张力为正、初始/最终残差有限。

旧 `stage3_quantitative_summary.json` 中 ANCF `min_tension_N=0` 是旧 runner 字段生成前的审计值，不能采信；MATLAB 直接复核当前高张力初始化中点张力约 `1.0e8 N`。后续新闭环 CSV 必须包含 `reference_tension_N`、`min_dynamic_tension_increment_N`、`max_dynamic_tension_increment_N`、`compression_risk` 和相对残差字段。
