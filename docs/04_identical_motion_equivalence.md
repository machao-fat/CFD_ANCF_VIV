# 原生解析运动与 ancfFileMotion 同轨迹等价性

## 案例定义

`online_motion_ab2_native` 与 `online_motion_ab2_file` 从同一 `0/constant/system` 副本派生，仅替换 `dynamicMeshDict` 的运动函数。两者使用相同网格、初始 `U/p`、`pimpleFoam`、`backward`、`dt=0.0025 s`、PIMPLE 配置、输出精度和 `forces/forceCoeffs` function object。文件式案例逐步发布

`y=0.1 sin(1.00530964914873 t)`

并由 `ancfFileMotion` 逐步消费，未预加载整张运动表。

## 量化结果

证据：`results/04_identical_motion_equivalence/identical_motion_equivalence.json` 和 `per_step_force_comparison.csv`。

| 量 | 结果 |
|---|---:|
| 对比步数 | 401 |
| 终止时间 | 1.0 s |
| 最大时间误差 | 0 |
| 轨迹最大误差 | 0 m |
| Fx RMSE | 0 N |
| Fy RMSE | `1.68e-8 N` |
| Fy 相对 RMSE | `1.08e-11` |
| 网格点文件数值最大差 | 0 |
| U 数值 token 最大差 | `1.0e-11` |
| p 数值 token 最大差 | `1.0e-9` |
| forceCoeffs 行数 | 401 |

因此“在线文件运动不能复现解析运动”这一项在修复后的严格同初场案例中通过；旧 `5.55%` 结果来自旧案例未真正启用动网格/初始状态不一致，不能继续作为接口误差。

## 初始确认修复

`ancfFileMotion` 的初始快照确认由 `consumedFile` 开关触发，`consumedDirectory` 只决定逐步确认文件的目录。缺少前者会造成发布器等待 step 0 而 CFD 等 step 1。当前案例同时配置两者，并检查 `motion_consumed_0.json`。

## 尚缺证据

本轮严格 A/B 尚未完成中途 CFD restart 前后自动差分；旧在线长回放已经完成从 step 16200 到 25000 的文件式 restart，但不是严格 native/file 同初场 A/B。故本项总体为“接口等价通过，restart 等价待补”。
