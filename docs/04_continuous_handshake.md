# 连续文件握手闭环

每个物理步执行：结构预测 → 原子提交 `motion.csv/motion_ready` → OpenFOAM 校验 step/time/SHA-256 并移动网格 → function object 写 `forces.dat` → 监控器发布完整 `slice_loads.csv/load_ready` → 结构校正。CFD 读取不到当前 step、发现跳步、NaN/Inf 或超时即停止，不复用旧载荷。

`ancfFileMotion` 采用 `consumed/motion_consumed_<step>.json` 做逐步确认，避免 DrvFs 上覆盖同名确认文件的竞态；二维模式默认只使用 x/y，z 只有显式 `useZMotion true` 才参与网格位移。等待下一步 ready 具有有限超时。

EB 运行：`results/04_single_slice_eb_fsi_run7/coupling_audit.csv`，1000 步至 `t=2.5 s`；ANCF 运行：`results/04_single_slice_ancf_fsi_continuous_run2/coupling_audit.csv`，同样 1000 步至 `t=2.5 s`。两者均完整结束并保存中点 MATLAB checkpoint。
