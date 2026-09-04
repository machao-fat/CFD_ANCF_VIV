# Fresh C++ t=0 三切片启动入口

本目录绑定的是全新 C++ 静态平衡状态和三切片模板，不复用旧 Stage 233/559 checkpoint。
当前窗口固定为 `global_step=0 -> 40`、`time=0 -> 0.05 s`、`global_dt=0.00125`。

## 先做离线预检

```powershell
cd "D:\研二文件\开题准备\CFD_ANCF_VIV"
python ".\tools\cpp_worker_fresh_t0_v1\prepare_fresh_t0_real_launch_v1.py"
Get-Content ".\results\239_cpp_worker_fresh_t0_real_preflight_v1\fresh_t0_real_launch_preflight.json"
```

预检必须显示：

```text
STAGE4F_D_CPP_WORKER_FRESH_T0_REAL_PREFLIGHT_V1_GATE: pass
launch_performed=false
MATLAB=0, OpenFOAM=0, WSL=0, CFD=0
```

## 真实启动

只有获得新的明确真实计算授权后，才执行：

```powershell
cd "D:\研二文件\开题准备\CFD_ANCF_VIV"
python ".\tools\cpp_worker_fresh_t0_v1\run_authorized_fresh_t0_001.py"
```

上面的命令只会拒绝启动。取得新的明确真实计算授权后，必须显式加入授权开关：

```powershell
python ".\tools\cpp_worker_fresh_t0_v1\run_authorized_fresh_t0_001.py" --authorize-real
```

该命令会启动一个 C++ worker 和三个 OpenFOAM/WSL slice 进程，执行固定 40 steps 后清理 owned 进程并写入：

```text
runtime\cpp_worker_fresh_t0_v1\real_run_001
results\240_cpp_worker_fresh_t0_real_v1
docs\240_cpp_worker_fresh_t0_real_v1
```

它不会启动 MATLAB，也不会自动扩展到更大的时间窗；失败时不会在同一 runtime 重试。

## 进度与结果

```powershell
Get-Content ".\results\240_cpp_worker_fresh_t0_real_v1\confirm_summary.json"
Get-Content ".\results\240_cpp_worker_fresh_t0_real_v1\stage4f_d_cpp_worker_fresh_t0_real_v1_gate.json"
Get-Content ".\results\240_cpp_worker_fresh_t0_real_v1\phase_timing_per_step.json"
```

真实启动前后的 MATLAB/OpenFOAM/WSL/CFD 进程数和 `owned_residual` 会写入 Gate。旧证据、旧 runtime、物理参数、全局时间步和正式 0.2.1 语义均保持只读。
