# Stage 4F-C 稳定化物理时间一致性候选离线设计报告

## 终态

- `STAGE4F_C_TIME_CONSISTENT_STABILIZER_DESIGN_V1_GATE: pass`
- `STABILIZER_TIME_CONSISTENCY_DIAGNOSIS: classified`
- `STAGE4F_C_NUMERICAL_ACCEPTANCE_STATUS: still_blocked_pending_new_authorization`
- 分类：`mixed_raw_and_stabilizer_time_sensitivity`

本 Gate 只表示离线设计、历史序列回放和故障注入完成。没有启动 MATLAB、OpenFOAM、WSL 或真实 CFD，不能替代 Stage 21 Gate。

## 当前路径审计

生产 hook 使用固定步权重：

`applied[n+1] = 0.9 * applied[n] + 0.1 * raw[n+1]`

`last_time_tick` 只保存身份，不进入公式。A 在 0.0025 s 内更新一次，C 更新两次，因此旧状态在同一物理时间的权重分别为 0.9 和 0.81。该差异是按 sample count 推进的确定性时间不一致。raw 输入、applied 输出、结构 correction 与 commit 位于同一 global-step 末端时间层，不访问未来数据。

## 候选协议

候选 B/D 是可回放的最小时间一致方案：

`old_weight = exp(-dt/tau)`

`applied(t+dt) = old_weight * previous + (1-old_weight) * raw(t+dt)`

为保持 A 的原行为，`tau = -0.0025/log(0.9) = 0.0237285 s`。C 半步新信息权重为约 0.0513167，两次半步合成后的旧状态权重严格等于 0.9。raw force 不变，状态保存 force、last tick、schema 和 hash；reset、rollback、restart 必须原子恢复 force 与物理时间 tick。

候选 A 是物理时间状态更新总协议；C 是累计物理时间窗口；E 冻结 predictor/corrector 时间层；F 只在共同 integer tick 做因果诊断。所有会改变生产数值行为的候选都需要新物理合同授权，本阶段未实施。

## 历史序列回放

原始 raw 冲量差保持不变：x 为 2.71465%，y 为 10.32390%。因此 raw y 的失败不能由离线 stabilizer 消除。

原固定步回放严格复现旧 applied 结果：x 为 17.64223%，y 为 12.50379%。时间一致指数候选得到 x 为 5.61656%，y 为 4.30853%。候选显著消除了额外的 sample-count 放大，但 x 仍略高于冻结 5% 阈值，且 raw y 仍失败。

共同时间点首次超过 5% 仍在 t=1.510 s，A step 0 / C step 1。固定步回放最先报告 slice 0/x（32.31%），指数候选同点 slice 0/x（21.06%）；Stage 22 raw 首个差异仍是该时间的 slice 1/y。候选不访问未来数据。

## 可修复与不可修复

可修复部分是固定 alpha 导致的 applied-state 步数依赖。不可由离线稳定化修复的是 raw CFD 瞬态步长敏感性。即使时间一致候选通过全部离线测试，也必须在新授权下修改冻结稳定化合同，并运行新的真实 A/C CFD 才能评价数值接受性。

## 测试

- `python -m compileall -q src tests`: pass
- Stage 23 专项：8/8 pass
- Stage 16-22 相关离线测试：全部 pass
- 根目录无过滤 unittest：855/855 OK，0 failure，0 error

故障注入覆盖不同比例 dt、非均匀 dt、rollback/restart、duplicate/missing sample、future access、NaN/Inf、时间倒退、tick/time 不一致、raw/applied 分离、schema/hash 和非法参数 fail closed。

## 证据完整性

父 checkpoint 实际 SHA-256 为 `5db86ae104015d51a8268862a1551579d96d0d80d82ddc7f55536371efc0334e`，与 Stage 20/21 runner 引用及历史接受值一致。任务文本给出的字符串在该位置写成 `...d80ddc7f...`，与文件实际 hash 不同；审计保留实际值，没有替换或改写旧证据。

Stage 20 A、Stage 21 C、生产 hook 的复算 hash 已写入 `evidence_hash_audit.json`。Stage 20/21 文件保持只读未修改。

## 最小下一步

需要用户明确授权：冻结 `alpha(dt)=1-exp(-dt/tau)` 的新稳定化物理合同、checkpoint schema 与 restart state 语义，然后先做生产接口故障测试，再进行全新 A/C 真实 CFD 数值验收。不得仅凭本离线结果接受 C。
