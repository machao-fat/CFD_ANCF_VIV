# Stage341 长时间运行准备（未启动）

前三个短窗口已完成，长时间运行必须重新获得明确授权。建议先以 `dt=0.005 s`、三切片、`inverseDistance 1(cyl)` 从全新零状态运行到 `80 s`（16,000 steps），作为约 15 个周期的候选统计窗口；是否达到正式收敛由已有统计 Gate 决定，不能由 runner 自动扩大时间窗。

启动命令（收到授权后执行）：

```powershell
cd "D:\研二文件\开题准备\CFD_ANCF_VIV"
& "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" ".\tools\stage336_dt005_one_second_qualification_v1\run_stage336_dt005_one_second.py" `
  --runtime ".\runtime\stage341_dt005_long_convergence_v1" `
  --results ".\results\341_dt005_long_convergence_v1" `
  --dt 0.005 --steps 16000 `
  --stage-id "stage341_dt005_long_convergence_v1" `
  --run-id "s341_dt005_three_slice_80s_v1" `
  --case-id "c341_dt005_three_slice_80s_v1"
```

预计墙钟：按 Stage338 实测约 `7.37 min / physical second`，80 s 约 `9.8 h`；考虑后期迭代变化，给出 `9–12 h` 区间。该命令会保留 rolling OpenFOAM 场、20 条结构尾记录、每 100 步 checkpoint 和标量收敛摘要，不保存完整历史场。MATLAB=0；会启动 3 个 OpenFOAM、1 个 C++ worker 和 1 个 WSL launcher。

启动前必须再次确认磁盘空间和无残留进程。运行期间可读取 `runtime/stage341_dt005_long_convergence_v1/logs/progress.json`、`structure_participant.json`、`checkpoint.jsonl` 及三个 slice 的最新数值时间目录。当前仍未启动；本文件只记录准备方案。
