# Stage 4C-A 主Agent验收结论

- 验收日期：2026-08-10
- 判定：**通过（仅限三至五切片 mock/合成可扩展性、空间非均匀载荷与统一事务验证）**
- 正式协议：0.2.1，未变更

## 1. 主Agent复核结果

- 全项目 Python 测试：`147/147` 通过；
- `python -m compileall -q src tests`：通过；
- 三、五切片的 manifest/config 均由正式 `SliceManifest`、`RuntimeConfig` 重新读取和验证；四个存储哈希与正式类重算值一致；
- 三切片、五切片各完成 10 个 mock 耦合步和 10 个 committed checkpoint；
- 独立审计 20 个最终 checkpoint manifest 引用的 660 个文件，SHA-256 和字节数全部一致；
- 三切片、五切片连续 10 步与 `5+5` restart 的选定状态最大绝对误差均为 `0`；
- 两组各 29 项失败/恢复测试满足 fail-closed，失败后结构不推进；
- 合成载荷的 `F_i=f_i^(2D) * slice_length_m` 独立重算误差为 `0`；
- 最大虚功相对误差为 `1.1102230246251565e-16`；
- 2/3/5 切片 mock 文件交换和 checkpoint 规模平稳增长，未发现异常的超线性跳变。

## 2. 冻结决定

Stage 4C-B 真实三切片任务必须使用以下三切片几何 manifest，不得由执行子任务自行改变：

- 文件：`results/05_stage4c_scalability_tests/canonical_3slice_manifest_candidate.json`
- SHA-256：`d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`
- 切片中心：`[1.25, 5.0, 8.75] m`
- 切片长度：`[2.5, 5.0, 2.5] m`
- `unit_span_m=1.0 m`
- `R_GL=I`

五切片 manifest 仅保留为后续扩展候选，本 Gate 不批准真实五切片运行。

候选三切片 config 的正确完整哈希为：

`11321ace674fec7e0d54c326ceb0d48bf7b3f3296743b3bfc930ef565d819a02`

该 config 的 `start_time_s=0` 和 `timeout_s=0.2` 只作为 mock golden fixture，不作为真实 OpenFOAM 运行配置。Stage 4C-B 应基于相同 manifest、`dt_s=0.0025`、`coupling_iteration=0` 和 `explicit_weak` 生成真实运行时 config，并报告新的正式哈希。

## 3. 范围边界

本次通过不代表真实三切片 CFD 已运行，也不代表整根立管 VIV、锁定区、长期统计或空间变化水动力已经验证。真实三切片阶段必须继续复核案例新鲜度、桥接时间、不同切片物理参数、CFL、统一 checkpoint 和 restart。

既有 mapping/orchestration runner 在回归过程中重写了两个测试汇总 JSON；它们不是 Gate 4A 的正式真实 CFD 证据，本次不构成阻塞。后续任务应避免在原位更新历史汇总，新的运行结果必须写入独立 Stage 4C-B 目录。
