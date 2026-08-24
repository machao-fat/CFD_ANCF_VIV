# Stage 4D-A-v3 Re80 continuation completion report

## Scope

本报告只覆盖 Stage 4D-A-v3 的 developed-flow continuation/snapshot-alignment 子任务。它不宣称完成 100 步三切片耦合、真实耦合 restart、长时间 VIV 或锁定区验证。

正式协议仍为 `0.2.1`，冻结三切片 manifest 内的 `slice_manifest_sha256` 仍为 `d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`。v1/v2 cases、results、docs 和旧 runner 均未覆盖写入。

## Re80 continuation

Re80 从只读 v2 最终场 `239.999999999817987` 复制到独立 v3 case，使用 `startFrom latestTime` 继续；没有调用 `setFields`，没有改变 `deltaT=0.0025 s`、网格、PIMPLE 或物性。v3 每 200 个时间步（0.5 s）写快照，真实 pimpleFoam 以当前力时程估计的至少两个周期为 block 长度，自适应延长。

| 项目 | 结果 |
|---|---:|
| v2 来源场时间 | 239.999999999818 s |
| v3 最终实际场时间 | 314.999999999750 s |
| 物理上限 | 360 s |
| continuation block 数 | 4 |
| 新增合并力样本 | 126001（合并历史总样本） |
| 最大 CFL | 0.1645772346 |
| checkMesh | return code 0 |
| pimpleFoam 返回码 | 4/4 为 0，均正常结束 |
| 连续稳定评价点 | 3 |

前三个真实评价点中，约258.999999999801 s 的窗口仍有 `Cl RMS` 和峰峰值变化超限；约277.999999999783、296.499999999767、314.999999999750 s 连续三点满足稳定判据。因此停止于约315 s，而不是用拟合或外推替代真实 CFD。

最终 Re80 统计窗口（末端两个各含3个完整周期）为：

- 丢弃启动瞬态：19.8243657734 s；
- 覆盖启动后周期数：31；
- 主频：0.1073364084 Hz；零交叉频率：0.1080445320 Hz；
- `St=0.1341705105`；
- 平均 `Cd=1.3934779155`，`Cd RMS=1.3934780070`；
- `Cl RMS=0.0396623669`；
- 两窗口相对变化：平均 Cd 0.0385%，Cl fluctuation RMS 2.0101%，频率 0.3457%，Cl 峰峰值 1.5890%；
- `0.12 <= St <= 0.22`，所有稳定判据为真。

## Re80 identity

- merged force hash: `f5185bc946d912908bc8738b2e30519bcb710a79f562d3c44386303c9ec4db32`;
- developed-flow hash: `9b010c5d6d71162779ddf7eb4861521ef494de88776ea5f502e9aa0652a9a7e5`;
- final `U` hash: `1d2693d3234c7346531f22c137501a462f6a2b825b5177261ce9bf9400e2c381`;
- final `p` hash: `54cebafd1ee8939fbd55bcc1fe0cb6cfc7b1d0affb13d690f8ae46e813f9f45a`;
- final `phi` hash: `8b1246cf319439aa9a284e152eedbc6a3de2e7a7f454de285da09360b0135551`;
- final `uniform/time` hash: `9bb9616f08cbaad2cbadff62a40ea48ef1357c9e84d7206d12e8445e5d052da6`.

来源 v2 Re80 力历史 hash 在 v3 运行前后均为 `d3270abc98a3c48b66c7047ee212a6ffb0198fb230d2b3ff2d38eee83686a4b2`，证明 v3 continuation 未修改 v2 证据。

## Evidence

- `results/06_developed_flow_v3/re80/continuation_lineage_v3.json`
- `results/06_developed_flow_v3/re80/convergence_history_v3.json`
- `results/06_developed_flow_v3/re80/flow_summary_v3.json`
- `results/06_developed_flow_v3/re80/force_history_merged_v3.csv`
- `results/06_developed_flow_v3/re80/force_coefficient_history_v3.png`
- `results/06_developed_flow_v3/re80/cl_envelope_v3.png`
- `results/06_developed_flow_v3/re80/window_convergence_v3.png`

结论限于：Re80 continuation 与 v2 来源保持身份连续，并在约315 s 的真实 CFD 场上达到三点连续稳定判据。该结论不等于 Stage 4D 或长时间 VIV 通过。
