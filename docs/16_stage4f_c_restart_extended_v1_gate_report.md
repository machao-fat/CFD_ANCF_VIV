# Stage 4F-C restart 与十步短窗 Gate 报告

## 结论

独立 attempt3 通过。`1+2 restart` 与已接受连续三步基线逐项一致；通过该门禁后，新增 7 个物理步全部提交，总计形成从 1.5075 s 到 1.51375 s 的 10 步短窗。

本结论仅接受三切片短窗数值执行、restart 可重复性和 checkpoint 连续性，不构成涡脱落统计、VIV 稳定响应、锁定区、实验验证或 Stage 4E 物理验证。

## 修复边界

attempt2 的失败来自 OpenFOAM 在目标力行被消费后、owned solver 自然退出前继续刷新 `forces.dat` 元数据。独立 sidecar 在自然退出后重新解析唯一目标时刻，严格要求力三分量与已消费值相同，再使用原 `finish_step()` 校验终态 size、mtime 与 SHA-256。未修改生产 driver、正式协议、ANCF/EB 核心、冻结阈值或旧失败证据。

## Restart 身份

- first leg：复用只读的已验证 1 步 checkpoint。
- restart leg：2/2 步提交。
- 三步 `q/qdot/qddot` 最大相对 L-inf 误差：0。
- 三步 previous slice force 最大相对 L-inf 误差：0。
- 每步 24 项 CFD manifest 场哈希完全一致，共 72 项。
- 最大时间表示误差：2.220446049250313e-16 s，小于 1e-12 s。

## 七步扩展

step 3 至 step 9 全部提交，终点为 1.5137500000000002 s。计入复用 first leg 后，10 个提交候选的最大 CFL 为 0.03411047062712107，最大绝对 Cd 为 6.789706022754859，最大虚功相对误差为 4.386541894684592e-16，最大力转换相对误差为 0，最大位置差/D 为 9.326255821119229e-11，最大速度差/U 为 2.984401600622506e-7。

中间强耦合诊断迭代的最大绝对 Cd 为 12.524265573334125；该迭代未提交。冻结且已验收的强耦合合同要求最终收敛候选满足 Cd 门槛，中间有限值只作诊断，因此不把该值改写或冒充提交态结果。

## Checkpoint、进程与测试

- attempt3 新增 committed checkpoint：9 个；连同只读 first leg，短窗共 10 个。
- 最终 checkpoint SHA-256：`c27916359016ffbd09fef9d6eed19175a48dc85a1a11ee00f12664d240023fb0`。
- attempt3 owned process：335 启动、335 关闭、0 残留；计入只读复用 first leg 的完整十步证据为 380 启动、380 关闭、0 残留。非零返回码 0；最大 live candidate engine 为 1。
- `python -m compileall -q src tests`：通过。
- restart/终态力专项：23/23 通过。
- 根目录无过滤 unittest：787/787 通过，无 failure/error。
- 父 checkpoint SHA-256 复核仍为 `5db86ae104015d51a8268862a1551579d96d0d80d82ddc7f55536371efc0334e`。

## Gate

`STAGE4F_C_RESTART_EXTENDED_V1_GATE_RECOMMENDATION: pass`

`THREE_SLICE_TEN_STEP_SHORT_WINDOW_NUMERICAL_STATUS: accepted`

下一授权点仅为更长但仍受限的三切片瞬态窗口。五/九切片、长时 VIV、锁定区和实验/物理验证均不得进入。
