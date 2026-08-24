# Stage 4C-A 三至五切片可扩展性与统一事务候选报告

## 范围与结论边界

本报告记录 Stage 4C-A 的 mock/合成验证结果：三至五切片配置、空间非均匀载荷、统一 ready/consumed 屏障、原子 checkpoint、restart 约束、失败停止和规模统计。协议版本保持 `0.2.1`，未修改正式公共协议、mapping、driver、checkpoint、ANCF 核心或既有 Gate 4A 证据。

本任务没有运行真实多切片 OpenFOAM，也没有运行长时间自由 VIV；因此不构成整根立管 VIV 验证。候选 manifest/config 已生成，是否正式冻结由 Sol 主Agent决定。

## 候选配置与 golden hash

| 配置 | 切片 `(slice_id, s_ref_m, slice_length_m, unit_span_m)` | 总长度/覆盖 |
|---|---|---|
| 3-slice | `(0,1.25,2.5,1)`, `(1,5.0,5.0,1)`, `(2,8.75,2.5,1)` | `10.0 m`，`[0,2.5] ∪ [2.5,7.5] ∪ [7.5,10]` |
| 5-slice | `(0,0.5,1.0,1)`, `(1,2.0,2.0,1)`, `(2,4.5,3.0,1)`, `(3,7.25,2.5,1)`, `(4,9.25,1.5,1)` | `10.0 m`，连续、无重叠、无间隙 |

两组均使用 `reference_length_m=represented_length_m=10.0` 和 `R_GL=I`。五切片的中心与区间分别为 `[0,1]`, `[1,3]`, `[3,6]`, `[6,8.5]`, `[8.5,10]`。所有中心均可作为 ANCF 非节点位置处理。

| 配置 | `slice_manifest_sha256` | `config_sha256` |
|---|---|---|
| 3-slice | `d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3` | `11321ace674fec7e0d54c326ceb0d48bf7b3f3296743b3bfc930ef565d819a02` |
| 5-slice | `0e0fdf93b77741715325ff1fee1b62ef02ca02a11747a26031e260bb34a2d6c4` | `39fbf310571aaf90a356162ee5c8253d9d4c864023f281a8afe5f269b83dd2ba` |

存储 hash 与正式类重新计算一致；canonical 文件见 `results/05_stage4c_scalability_tests/canonical_*_candidate.json`。

## Mock campaign 与 restart

3-slice 和 5-slice 均完成连续 10 个结构步。每步均发布 N 个 motion、收到 N 个 motion consumed、收到 N 个 load ready、发布 N 个 load consumed、执行一次结构 mock correct，并提交一个统一 committed checkpoint。

| 配置 | 完成步数 | motion CSV | load CSV | marker JSON | committed manifest | 结构推进 |
|---|---:|---:|---:|---:|---:|---|
| 3-slice | 10 | 30 | 30 | 60 | 10 | 正常完成 |
| 5-slice | 10 | 50 | 50 | 100 | 10 | 正常完成 |

连续 10 步与 5+5 restart 的 `step/time/q/qdot/qddot/上一步切片力/广义力/transaction state/manifest hash/config hash` 选定状态均严格一致，最大绝对误差为 `0.0`。

## 失败注入与事务语义

3-slice 和 5-slice 各覆盖 29 个注入项：motion 未消费、load 缺失、时间/step/iteration 错误、payload/config/manifest hash 错误、NaN/Inf、超时、重复 slice ID、8 类 checkpoint 文件缺失、checkpoint prepare 失败、atomic publish 失败、post-commit finalize 失败，以及 restart 数量/坐标/长度/config 变化和仅顺序变化。

- 两组均 `all_fail_closed=true`，`structure_advanced_on_failure=false`。
- 所有 pre-commit 失败均没有 committed manifest。
- post-commit finalize 失败保留 1 个 committed manifest，进入 `RECOVERY_REQUIRED`；恢复后同一 step 重复推进被拒绝，随后 step 1 可继续。
- restart 仅改变输入顺序但保持 slice 身份时被接受，物理身份未被重新解释；数量、坐标、长度或 config hash 改变均被拒绝。

## 可扩展性统计

以下为 10 步合成事务的 wall-clock 统计；目标是发现超线性异常，不是严格线性证明。内存指标没有可靠的跨平台采样器，按要求记为 unavailable。

| 切片数 | 总耗时 (s) | 平均步耗时 (s) | hash 重算 (s) | exchange (bytes) | checkpoint (bytes) | transaction log (bytes) |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | `0.7822780` | `0.0782278` | `0.0004879` | `100776` | `66351` | `40739` |
| 3 | `1.1108034` | `0.1110803` | `0.0005452` | `144031` | `90355` | `53434` |
| 5 | `1.8101535` | `0.1810154` | `0.0006591` | `227793` | `138053` | `77304` |

文件数量按切片数增长：2/3/5 的 motion/load CSV 为 `20/30/50`，marker JSON 为 `40/60/100`，committed manifest 均为 10。未观察到异常的规模跃迁；这些是本机 mock 文件系统指标，不是 CFD 计算性能结论。

## 回归测试

本轮实际运行：Stage 4C-A 新增测试 `24/24`；mapping `49/49`；driver `7/7`；restart `4/4`；integration `13/13`；全项目 Python 测试 `147/147`；`python -m compileall -q src tests` 通过。详细命令和数字见 `results/05_stage4c_scalability_tests/regression_summary.json`。

## 未完成事项、风险与交接

未完成事项：真实三切片 OpenFOAM–ANCF 闭环、长时间自由 VIV、CFD 并行资源/峰值内存测量，以及候选 manifest/config 的正式冻结。

遗留风险：当前结构为确定性 mock adapter；空间载荷为合成单位跨距力；真实 CFD 的进程新鲜度、动态网格稳定性和 ANCF runner 的生产状态导出仍需 Sol 在后续 Stage 4C-B 任务中复核。

主Agent应复核的文件：本报告、`05_stage4c_spatial_nonuniformity_report.md`、`results/05_stage4c_scalability_tests/` 下的候选 JSON、mock/restart/failure/scalability/regression JSON，并确认禁止路径未被本任务改写。

**STAGE4C_A_GATE_RECOMMENDATION：建议通过**（仅表示建议 Sol 复核 Stage 4C-A 候选证据，不宣布 Stage 4C 通过）。
