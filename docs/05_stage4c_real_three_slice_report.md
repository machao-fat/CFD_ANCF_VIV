# Stage 4C-B 真实三切片 OpenFOAM–ANCF 短时弱耦合报告

## 范围与边界

本报告记录真实三切片 OpenFOAM 10 `pimpleFoam`–ANCF 显式弱耦合的短时候选证据。运行从独立 warm-up 末端 `t0=0.05 s` 开始，完成均匀来流 3 个全局步、空间非均匀来流连续 3 个全局步，以及 step 0 checkpoint 后恢复 step 1–2。没有运行长时间自由 VIV，也不宣称整根立管 VIV 验证或 Stage 4C 通过。

## 冻结输入与运行配置

- 协议版本：`0.2.1`；case：`stage4c_candidate_3slice`；manifest SHA-256：`d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`。
- 切片：`(0, 1.25, 2.5, 1.0)`、`(1, 5.0, 5.0, 1.0)`、`(2, 8.75, 2.5, 1.0)`；长度和为 `10.0 m`，覆盖 `[0,2.5]`、`[2.5,7.5]`、`[7.5,10]`。
- `R_GL=I`、`dt=0.0025 s`、`coupling_iteration=0`、`coupling_scheme=explicit_weak`、runtime config SHA-256：`f92460d05f4a5cf1442e241fae21f993b8693d9e54a36f5e9f76f9caa3df566e`。
- uniform 物理配置 SHA-256：`bd4f062c3c09e07e2e949fbc6c06bdeeebea4f7c9f7be539b65ce6c1fe46295d`；nonuniform 物理配置 SHA-256：`99ce9cd5bb22eb4dc4562fc890049ea12634eb10376ecef19b6342b8f14505c2`。
- 每个 slice 使用 fresh case；OpenFOAM 进程串行调度，最大并发 `1`，未超过 2。

## Bridge 时间映射

初始 seed 为 `(bridge_step=0, t=0.05 s)`。目标记录为全局 step 0→`(bridge_step=1, t=0.0525 s)`、step 1→`(2, 0.055 s)`、step 2→`(3, 0.0575 s)`；未使用 `time-dt` 替代目标时间。三切片均通过当前 step、time、iteration、freshness 和 hash 审计。

## 均匀来流真实结果

均匀来流速度为 `U=(1.0,1.0,1.0) m/s`。step 0 的单位跨距力和切片总力如下：

| slice | `f^(2D)` (N/m) | `F` (N) |
|---:|---|---|
| 0 | `[1678.187177582911, -88.82565842953716, 7.279962797179097e-17]` | `[4195.467943957277, -222.0641460738429, 1.8199906992947743e-16]` |
| 1 | `[1678.187177582911, -88.82565842953716, 7.279962797179097e-17]` | `[8390.935887914555, -444.1282921476858, 3.6399813985895486e-16]` |
| 2 | `[1678.187177582911, -88.82565842953716, 7.279962797179097e-17]` | `[4195.467943957277, -222.0641460738429, 1.8199906992947743e-16]` |

完成 `3` 步，`3` 个 checkpoint，均为 committed、每个 26 objects；最大 CFL `0.1751576958783445`。

## 空间非均匀来流真实结果

三个 fresh case 的来流速度为 slice 0/1/2：`0.8/1.0/1.2 m/s`，对应 `Re=80/100/120`。step 0 结果：

| slice | `f^(2D)` (N/m) | `F` (N) |
|---:|---|---|
| 0 | `[1332.2418863647958, -66.15228861143589, 4.386635386000902e-17]` | `[3330.60471591199, -165.38072152858973, 1.0966588465002255e-16]` |
| 1 | `[1678.187177582911, -88.82565842953716, 7.279962797179097e-17]` | `[8390.935887914555, -444.1282921476858, 3.6399813985895486e-16]` |
| 2 | `[2026.9116590971526, -112.70493939231233, 1.0804696886259463e-16]` | `[5067.279147742882, -281.7623484807808, 2.701174221564866e-16]` |

三个单位跨距水动力不相同，三个切片总力也不相同；后续 step 1–2 仍分别从三个真实 case 提取。连续运行完成 `3` 步，最大 CFL `0.2103444737377753`。

## `Δs` 与映射审计

正式 `LoadRecord.from_conversion` 负责一次 `F_i=f_i^(2D)×slice_length_m`，随后复用正式 `build_H_for_manifest` 和 `map_integrated_slice_forces` 执行 `Q=ΣH_i^T F_i`。本次全量 step/slice 审计的最大绝对换算误差为 `0.0` N；未发现重复乘以 `Δs`。ANCF 结构由现有核心函数推进，没有复制 H/Hᵀ 或 hash 实现。

## 进程与文件规模

实际 OpenFOAM 日志中的 `ExecutionTime/ClockTime` 已收集到 `stage4c_b_candidate_summary.json` 的 `process_scheduling`。uniform 为 `9` 个 slice-step 进程，solver clock time 合计 `8.0` s，exchange/checkpoint bytes 为 `46484/76560`；nonuniform 连续为 `9` 个进程，solver clock time 合计 `7.0` s，exchange/checkpoint bytes 为 `46476/77191`。实际最大并发为 1，peak memory 未伪造，记为 unavailable。

最大 CFL 为 uniform `0.1751576958783445`、nonuniform `0.2103444737377753`，均小于 0.8；全部运动记录中最大单步分量增量为 `0.0028255627310240783` m，小于 0.05 m；按 `0.5*rho*U^2*D` 归一化的最大 `|Cd|/|Cl|` 分别为 uniform `4.835948458656404/0.2975866241683319`、nonuniform `4.8369278787193934/0.29703304501871214`，均小于 10。

## 统一 checkpoint 与 restart

每个三切片 checkpoint 包含 3×(motionScale + U/p/phi/Uf/meshPhi/points/uniform/time) + 2 个 ANCF 结构对象，即 26 objects。完整文件级 SHA-256 审计见 `results/05_stage4c_real_three_slice_tests/checkpoint_hash_audit.json`，结果为 `passed`。

非均匀连续基线为 step 0–2；分段路径先完成 step 0，再从该 checkpoint 恢复并完成 step 1–2。比较结果为 `completed`：time、q/qdot/qddot、hydrodynamic force、U、p、points、phi、Uf、meshPhi、uniform/time 和 motionScale 均严格一致；最大 ANCF 相对误差 `0.0`，最大水动力相对误差 `0.0`，最大 U/p 相对误差 `0.0`，最大 points 绝对误差 `0.0` m。

## 回归与未完成事项

新增 Stage4C-B 静态测试 16/16；mapping 49/49；driver 7/7；restart 4/4；multi-slice integration 13/13；Stage4C-A scalability 24/24；全项目 Python unittest 163/163；`python -m compileall -q src tests` 通过。真实三切片不包含长时间自由 VIV、并行 CFD 性能评估或正式 manifest 冻结决定；这些留给 Sol 主Agent 复核和后续任务。

候选交接摘要：`results/05_stage4c_real_three_slice_tests/stage4c_b_candidate_summary.json`。本报告只给出候选证据和 `建议通过`，不宣布 Stage 4C 通过。
