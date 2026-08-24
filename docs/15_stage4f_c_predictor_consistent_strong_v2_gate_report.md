# Stage 4F-C predictor-consistent 强耦合三步预检

## Gate 结论

本阶段达到 `success_three_step_predictor_consistent_strong_preflight`，仅接受三步短窗数值预检。不得据此宣称涡脱落统计、VIV 稳定响应、锁定区或物理验证完成。

## 方法修正

v1 将 predictor 几何上的 CFD 场与 corrector ANCF 状态写入同一 checkpoint。v2 使用独立 sidecar 冻结 predictor native MAT、`q/qdot/qddot` 和发布给 CFD 的 motion，并在 promotion 前恢复同一 predictor。原子 checkpoint 因而保存同一 predictor 的结构状态和 CFD 场；actual observed CFD force 仍作为下一步载荷历史。正式 `0.2.1` 源码未修改。

外层固定点采用 `alpha=0.5`、最多 12 次候选、绝对残差不超过 `25 N`、相对残差不超过 `1e-3` 且连续两次满足。有限的中间候选 `Cd` 只作迭代诊断，最终收敛候选仍必须满足 `|Cd|<=10`。CFL、非有限值、FATAL、负体积、几何、速度、虚功和力转换门槛仍逐候选硬停止。

## 真实结果

三个物理步均完成，时间范围为 `1.5075–1.509375 s`。每步执行 9 个候选并选择第 8 个：

- step 0：最终 `max|Cd|=6.7897060`，残差 `3.715535 N / 6.56677e-5`
- step 1：最终 `max|Cd|=6.7164512`，残差 `7.462561 N / 1.33330e-4`
- step 2：最终 `max|Cd|=3.8471796`，残差 `5.935933 N / 1.85152e-4`

全部 27 个候选的最大 CFL 为 `0.03411047`，最大位置差 `2.14471e-6 D`，最大速度差 `0.00686306 U`，最大虚功相对误差 `3.67940e-16`，力转换误差为 `0`。三个 predictor coherence 审计均通过，生成三个 unified committed checkpoint。

中间候选最大 `|Cd|=12.52427`，但固定点继续收敛后的最终候选满足原 `|Cd|<=10` 门槛。这一调整是 v2 明示的新数值合同，不回写或篡改 v1 失败证据。

## 测试与进程

`compileall` 通过，v2 专项 `11/11`，根目录无过滤 unittest `768/768`。27 个候选共登记 135 个 owned 进程实例，全部关闭，残留 0，非零返回码 0；最大候选并发为 1。

## 范围限制

本结果只证明三步 predictor-consistent 分区固定点事务可执行并满足冻结数值门槛。尚未验证 restart、时间步敏感性、延长瞬态、五/九切片、长时 VIV、锁定区或实验一致性。下一步只能在新授权下进入短窗 restart 与延长瞬态设计。
