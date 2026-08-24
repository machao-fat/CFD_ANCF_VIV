# Stage 25 时间一致稳定化合同修复失败报告

`STAGE4F_C_TIME_CONSISTENT_STABILIZER_CONTRACT_REPAIR_V1_GATE: do_not_pass`

唯一终态为 `probe_P_transaction_identity_failure`。

Stage 23 immutable contract 原始 tau `0.023728053952574758` 已通过严格 parser 提取，源 hash 为 `d24b089822478160986b93584f391dbe636de164994411938da5b5e850e77369`。canonical contract hash 为 `cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78`。`alpha(0.0025)` 的 Decimal 结果与 0.1 的绝对误差为 `1.7382920364348068e-18`，两个半步旧状态权重组合与 0.9 的误差同量级，低于运行前冻结的 `5e-17`。Stage 24 错误 tau 被 parser 拒绝。

raw snapshot manifest 已扩展为真实 path/canonical path/SHA-256/size/mtime/run/case/step/slice/tick/schema/creation transaction/consume transaction/immutable/kind，并在离线篡改、路径越界和 identity 测试中 fail closed。

生产编辑前后根目录 unittest 均为 867/867 OK。P 启动后，三个 slice 和 MATLAB correct 均返回 0，但 checkpoint prepare 发现 scheduler run_id=`stage25_probe_P`，真实 artifact run_id=`stage4f_timestep_diagnostic_v3_d2`，严格拒绝 `raw force snapshot manifest identity mismatch`。未生成 committed checkpoint，stabilizer committed state 未推进。P 完成 0/6 步；Q、A/B/C 未启动。同一 runtime 未重试。

owned process 为 MATLAB 2/2/0、WSL/OpenFOAM 3/3/0。三个 immutable raw snapshots、solver logs、transaction log、PID registry 和 partial case 均保留。

最小修复需要新的授权 attempt：在 factory 创建时统一 process、scheduler、artifact 和 checkpoint 的显式 run_id，而不是在 factory 后仅覆盖 scheduler.run_id；增加该真实 adapter identity 集成测试后重新运行 P。不得复用本次 partial case。
