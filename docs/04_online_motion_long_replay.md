# 在线规定运动长周期回归

回归轨迹为 `y=A sin(ωt)`，`A/D=0.1`、`f=0.16 Hz`、`dt=0.0025 s`，目标为 25000 步、62.5 s、10 个完整周期。解析运动案例和 `ancfFileMotion` 文件式案例使用同一 OpenFOAM 网格、物性、动网格和力积分对象；文件端逐步发布、逐步确认，不把整段表格一次性交给 CFD。

最终证据目录为 `results/04_online_motion_long_replay_run8/` 和 `cases/openfoam/online_motion_long_replay_run8/`。该目录保存 publisher、载荷监控器、OpenFOAM 日志、逐步 consumed marker 和 force history。若最终 status 未写出，则该项只能记为进行中，不能以中间步数宣称十周期通过。

已有单步解析/在线同轨迹力一致性证据见 `results/04_single_slice_weak_coupling/online_motion_smoke_summary.json`；本长周期回归用于补足“连续多步”欠项。
