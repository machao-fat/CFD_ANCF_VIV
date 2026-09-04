# Stage 372: C++/preCICE 三切片续算

本阶段只执行已授权的 `80.2 s -> 200.0 s` 续算，`dt=0.005 s`、三切片、23,960 步。初始场来自只读保护的 Stage 370 `80.2` 末态；不复用 Stage 367 失败 runtime，不改变 ANCF/EB 核心、物理参数或统计阈值。

## 启动

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\stage372_cpp_worker_precice_three_slice_80p2_to200_v1\start_stage372.ps1"
```

启动器只会创建新的 runtime，并在后台启动 Python launcher；launcher 再在 WSL 中启动 OpenFOAM 10、C++ worker 和三个 preCICE participant。MATLAB 启动数为 0。

## 查看进度

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\stage372_cpp_worker_precice_three_slice_80p2_to200_v1\get_stage372_status.ps1"
Get-Content ".\runtime\stage372_cpp_worker_precice_three_slice_80p2_to200_v1\logs\checkpoint.jsonl" -Tail 5
Get-Content ".\runtime\stage372_cpp_worker_precice_three_slice_80p2_to200_v1\logs\returns.txt"
```

实际 runtime 为 `runtime/stage372_cpp_worker_precice_three_slice_80p2_to200_v1_retry3`。`progress.json` 中的 `current_global_step` 和 `current_time_s` 是结构端已提交的进度；`slice_counts` 应保持三个切片相同。运行期间仅保留 `purgeWrite=1` 的最新场、低容量 checkpoint/进度/质量日志和末尾审计记录。

## 预计墙钟

Stage 370 的 40 步约 78.83 秒。按此基线，23,960 步约 13.1 小时；考虑启动、I/O 和负载变化，预计约 13--15 小时。前 100--200 步可用实际速率更新估计。

## 失败策略与状态

任一 participant、OpenFOAM 或 worker 非零退出、NaN/Inf、时间/身份不一致或 preCICE 断连都会 fail-closed；不在同一 runtime 自动重试。`returns.txt`、stderr、PID 和质量 JSON 会保留。正式统计仍为 `FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`，本阶段完成不等同于正式收敛证明。
