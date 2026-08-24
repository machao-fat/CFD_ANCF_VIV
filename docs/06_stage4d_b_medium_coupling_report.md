# Stage 4D-B 真实三切片 100 步 CFD–ANCF 中等步数报告

## 结论边界

本报告记录一次隔离的新鲜 run 的真实工程验证。它不构成锁定区、稳定振幅、整根立管 VIV 或长时间自由振动结论；最终 Stage 4D-B Gate 由 Sol 主Agent复核共享工作区文件、日志、hash 和测试后决定。

协议版本为 `0.2.1`，冻结三切片 manifest hash 为
`d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`。

## 输入身份复核

Stage 4D-A 入口文件为：

- `docs/06_stage4d_a_sol_acceptance.md`：`stage4d_b_entry=true`，范围限定为中等步数工程验证；
- `results/06_developed_flow_v3/developed_flow_bank_v3.json`：bank identity hash `5ed12fb1933d27baca9bc681ef21966341a93219cabd827c2a8225124c5cc8b7`。

流场来源和物理 hash 与入口证据一致：

| 切片 | 来源 | 快照时间/s | 入口物理 hash |
|---|---|---:|---|
| 0 / Re80 | `cases/openfoam/stage4d_developed_flow_v3/re80` | 314.99999999974978 | `9b010c5d6d71162779ddf7eb4861521ef494de88776ea5f502e9aa0652a9a7e5` |
| 1 / Re100 | `cases/openfoam/stage4d_developed_flow_v2/re100` | 188.49999999986483 | `2d2fc3edfdbcf12bc461721d3009d90c54801fdd3bd20649bdfc7799f81fd2e5` |
| 2 / Re120 | `cases/openfoam/stage4d_developed_flow_v2/re120` | 139.49999999990939 | `913e788e29c3ebf1361a4fd422dc8835cbb1b6814f81e51c5c609f9467552136` |

三组来源网格点 hash 均为
`04eee7b608ae1bdfc8dee54c66707c707cc8f1bde321e76d93675d5a4b5f1058`。
旧 motionScale hash `79ad02083d870f2b39fcbc8d0a9369ad8ff487a88832109d609af01355a330e4`
未被使用。

## 快照物化与动网格

campaign 为每个 run 创建全新 `cases/slice_0000..0002`，仅复制指定来源快照的网格、常量、系统和 `U/p/phi/uniform/time` 内容，随后将时间物化为局部 `t=0`，并将字段头位置改为 `location "0"`。没有调用 `setFields`，没有重新暖机，也没有跨 Re 复制场。每个目标 case 未携带历史 force、exchange、checkpoint、日志或 processor 污染。转换 lineage、源/目标 hash 和规则保存在各 run 的 `materialization/` 中。

当前网格初始生成的 `0/motionScale` hash 为
`30c7be5c4faa19a5c311e05585d20dcb0fe0af0b5f1292e8600a4cbb0aba046d`，大小 73,256 bytes、10,624 个有限值，三切片一致，值域为 `[0,1]`。OpenFOAM 首次读取并按其字段格式写回后，生产 case 和 committed checkpoint 中的规范化文件 hash 为 `833fd42be209a83a4b4fd4792dc5377168cd81814a2ba60013b6ce11776cc0a5`，大小 53,670 bytes；其 10,624 个数值仍全部有限且值域为 `[0,1]`。正式 run 与 restart 比较采用写回后的生产 hash，结果严格一致；两阶段文件均与同一个 `polyMesh/points` hash 配对审计通过。

## 初始水动力

从各自快照 force 时程末行读取二维单位跨距力，单位为 N/m；切片长度只应用一次：
`F_i = f_i^(2D) * slice_length_i`，`unit_span_m=1`。

| slice | `f_x,f_y` / N/m | `F_x,F_y` / N |
|---|---|---|
| 0 | `(445.8284384377145, 8.3762441942600)` | `(1114.5710960942863, 20.9406104856499)` |
| 1 | `(667.5050411845340, 17.1125122192822)` | `(3337.5252059226700, 85.5625610964111)` |
| 2 | `(933.1581284780705, -135.0436878522180)` | `(2332.8953211951760, -337.6092196305451)` |

源 CSV hash 分别为：Re80 `f5185bc946d912908bc8738b2e30519bcb710a79f562d3c44386303c9ec4db32`、Re100 `da07a7979ec03163eb9163d76fafdba59db62bead8b44ad7fead62f285b421d1`、Re120 `954a734c2c9d97ceb4e0dba36365114c7faddbd6f20f968cb9bd08618a960ba9`。

## 两步真实预检

预检 run：`stage4d_b_preflight_20260811T044234Z_9773dba10f`。

- 2/2 全局步、6/6 切片完成，所有返回码为 0，日志均有 `End`；
- 最大 CFL `0.1719161084229786`；
- Persistent MATLAB worker start count 为 1，初始化响应记录 worker PID `6796`；
- ProcessLimiter `max_processes=2`，实际峰值 2，区间重叠峰值 2，结束时 active=0，无 permit 泄漏；第三切片在许可不足时等待；
- 2 个 committed checkpoint；结构状态有限，motionScale/points 审计通过。

首次预检 run `stage4d_b_preflight_20260811T023156Z_cf5eab2215` 因新鲜 case 的动态网格 `fvSolution` 缺少 `pcorrFinal` 而被 OpenFOAM 非零返回停止。该失败证据保留；仅在新 run 的新鲜 case 中补齐所需动态网格求解器配置后重新预检通过，未修改只读模板或历史证据。

## 正式 100 步运行

正式 run：`stage4d_b_formal100_20260811T044351Z_7e8682bdbf`。

- 100/100 全局步，物理时间 `0.25 s`，300/300 切片执行；
- MATLAB worker PID `10032`，主 run `start_count=1`，无静默重启；
- ProcessLimiter 上限 2，实际峰值 2、区间计算峰值 2，结束 active=0，无 permit 泄漏；
- 最大 CFL `0.1725241657902625`，100 个 step 审计条目、300 个日志均正常结束，无 `FOAM FATAL`、`Fatal Error` 或 `SIGFPE`；
- 最大运动增量 `1.0915964891001567e-05 m`；最大横向位移 `5.2504409877299565e-05 m`；最大速度 `0.004482757857033917 m/s`；最大加速度 `0.7956041982353187 m/s^2`；
- 最大积分力绝对值 `3371.5220405995096 N`，最大单位跨距力绝对值 `963.3476900809184 N/m`；
- Newton 迭代数为 2，最大残差 `0.009274713643632165`，全部收敛；局部张力范围 `9964056.964575445` 至 `10000000.00611637 N`；
- 单步墙钟平均约 `7.202629127 s`，最大约 `12.478316700 s`。

每一步流程均为预测、运动发布、三切片 CFD、力校验、H^T 映射、校正、统一 checkpoint、结构 finalize。CFD 失败不会推进结构状态。每步预测/校正速度、单位跨距力、积分力、广义力、结构状态、Newton 和墙钟数据均保存在正式 run 的 `exchange/`、`checkpoints/` 和 `formal100_result.json`。

## checkpoint 与证据位置

正式 run 产生 100/100 个 committed manifest；每个 manifest 有 26 个审计对象，总计 2600 个对象，重新计算 hash 后全部有效，事务状态均为 `committed`。对象包括 OpenFOAM 字段、时间、网格点、motionScale 和 ANCF/全局事务对象。索引文件为：

`results/06_stage4d_medium_run/stage4d_b_checkpoint_hash_audit.json`。

正式结果索引文件为：

- `stage4d_b_100step_summary.json`
- `stage4d_b_energy_audit.json`
- `stage4d_b_process_concurrency_audit.json`
- `stage4d_b_candidate_summary.json`

其中 candidate summary 明确保留 `free_viv_claim=false` 和 `candidate_pending_sol_review`，不宣称长时间 VIV 结论。

## 回归测试

已运行专项测试 `python -m unittest discover -s tests/stage4d_medium_campaign -p 'test*.py'`：11 tests，0 failures；`python -m compileall -q src tests`：通过；全项目 `python -m unittest discover -s tests -p 'test*.py'`：234 tests，0 failures。测试和完整运行证据均由 Sol 主Agent复核后作为最终 Gate 输入。
