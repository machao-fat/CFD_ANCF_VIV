# Stage 4F-C-v3 Bridge 精度与 D2 时间步诊断报告

## 结论

`STAGE4F_C_V2_TIMESTEP_DIAGNOSTIC_GATE: do_not_pass`

唯一终态为 `failure_timestep_refinement_not_sufficient`。独立 v3 bridge 修复通过，D2 从同一父 checkpoint 真实完成 10/12 步，随后在 step 9 触发冻结的动态几何位置一致性门槛，未运行 dt/8、A/B/C 或 restart。

## Bridge 修复

旧库使用 C++ 默认流精度，将 `1.5081250000000002` 写成 `1.50813`。v3 独立库使用 `std::numeric_limits<scalar>::max_digits10`，D2 step 0--9 的 consumed marker 与目标时间严格一致，原有 `1e-12` 校验未修改。

## D2 结果

- `dt=0.000625 s`
- 时间范围：`1.5075 -> 1.51375 s`，完成 `10/12` 步
- 最大 CFL：`0.2494008076`
- 最大 `|Cd|`：`44372.6697610`
- 最大速度一致性误差：`21.8739530 U`
- 最大位置一致性误差：`0.0068356103 D > 0.005 D`
- 最大虚功相对误差：`3.8404645e-16`
- 最大力转换误差：`0`
- 已提交 checkpoint：`10`

Cd 和速度误差从第 1 步起增长，后期位置一致性成为首个阻断 Gate。CFD 日志均有 `End`，无 FATAL、NaN/Inf、负体积或浮点崩溃。

## 保护范围

旧证据、父 checkpoint、正式协议、ANCF 核心、阈值和 v2/v3 失败运行均保持只读。D2 运行产生的全部 case、日志、partial/committed checkpoint 和 PID 证据均保留。

该诊断不构成 Stage 4F-C 数值验收，也不代表稳定 VIV、锁定区或物理验证。

