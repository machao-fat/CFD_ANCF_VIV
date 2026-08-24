# Stage 4F-C 四十步受限延长 Gate 报告

## 结论

`STAGE4F_C_LIMITED_EXTENSION_V2_GATE: pass`

唯一终态为 `success_forty_step_limited_transient_and_final_window_restart`。从已接受 step 19 checkpoint 以四个五步原子块完成 step 20–39；四块全部通过并清理后，从 step 34 checkpoint 在 fresh case 中重跑 step 35–39。

## 关键数值

- 新 continuous：20/20 committed，`1.520000 -> 1.532500 s`。
- Final-window restart：5/5 committed。
- 从原始起点累计：40 步，0.025 s。
- 新阶段提交态最大 CFL：0.03382406349408694。
- 新阶段提交态最大绝对 Cd：1.2438482924799532。
- 最大虚功相对误差：6.198990578846362e-16。
- 最大力转换相对误差：0。
- 最大位置差/D：8.76821061835052e-11。
- 最大速度差/U：2.8058272400595916e-7。

## Restart 与磁盘审计

restart step 35–39 的 q/qdot/qddot 和 previous forces 相对误差均为0；每步24项 CFD 场哈希一致，共120项。

独立磁盘审计没有直接采用 runner 的 pass 字段，而是递归验证每步唯一 committed checkpoint、selected iteration、连续两次残差收敛、最终 Cd 接受、ANCF runner checkpoint SHA-256、唯一 slice 0/1/2 以及24项唯一 CFD 场。Continuous 外部 lineage 20条，restart lineage 5条，跨块父子哈希链通过。

父 checkpoint SHA-256 前后均为 `4da73e2a7a8d526fa41a12fc155790d2a361706f57f38403207164cfce7268a9`。

## 测试与进程

- `compileall`：通过。
- v2 专项：6/6。
- 根目录无过滤 unittest：805/805。
- owned process：490启动、490关闭、0残留；非零返回码0。
- 最大 live candidate engine：1。
- runtime及临时/偏好目录均位于D盘。

## 边界

`THREE_SLICE_FORTY_STEP_LIMITED_TRANSIENT_NUMERICAL_STATUS: accepted`

0.025 s仍远不足结构周期或脱涡统计窗口。本结果不是VIV稳定响应、锁定区、实验对比或物理验证。进一步三切片延长需要新授权；五/九切片和长时VIV不得进入。
