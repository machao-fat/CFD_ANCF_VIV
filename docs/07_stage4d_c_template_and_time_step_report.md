# Stage 4D-C-A 候选模板与时间步收敛报告

## 范围与冻结身份

本报告只覆盖 Stage 4D-C-A 的候选 OpenFOAM 模板、Stage 4D-B 基准复核、`dt=0.00125 s` 细时间步运行及共同时间点比较。协议仍为 `0.2.1`，三切片 manifest SHA-256 为 `d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`，developed-flow bank identity 为 `5ed12fb1933d27baca9bc681ef21966341a93219cabd827c2a8225124c5cc8b7`。

Stage 4D-B 正式基准目录只读复核为：

`D:\研二文件\开题准备\CFD_ANCF_VIV\results\06_stage4d_medium_run\stage4d_b_formal100_20260811T044351Z_7e8682bdbf`

复核值为 100 步、300 次切片执行、最大 CFL `0.1725241657902625`、MATLAB `start_count=1`、checkpoint `100/100`、`E_c=9.906678707660641e-05`。没有覆盖该目录或 Stage 4D-B 证据。

## 候选模板

新模板目录为 `cases/openfoam/stage4d_convergence_template`，不修改旧模板。模板参数包含 `dt_s`、`slice_id`、`U_mps`、`start_time_s`、`end_time_s`、`step_offset` 和 `run_id`。`fvSolution` 固化了 `pcorr`、`pcorrFinal`、`cellMotionUx`；动态网格配置固化了 `correctPhi yes` 和 `correctMeshPhi yes`，真实运行不依赖字符串临时修补。

模板 identity SHA-256：`a8eb20f0fcc6edb912fcc5bed0e9179396d90eacc5c3f3ff5182594606365050`。

最新真实两步烟测 run_id 为 `stage4d_c_template_smoke_20260811T085659Z_2b81b2476c`，三切片均正常完成 2 步，OpenFOAM 返回码为 0，最大 CFL `0.1719161084229786`，MATLAB 启动次数 1，ProcessLimiter 实测峰值 2，checkpoint 数 2。当前网格生成的 motionScale 初始 hash 为 `30c7be5c4faa19a5c311e05585d20dcb0fe0af0b5f1292e8600a4cbb0aba046d`，OpenFOAM 规范化生产 hash 为 `833fd42be209a83a4b4fd4792dc5377168cd81814a2ba60013b6ce11776cc0a5`；未使用旧不兼容 hash `79ad02083d870f2b39fcbc8d0a9369ad8ff487a88832109d609af01355a330e4`。

## 时间步运行与对齐

细时间步 run_id 为 `stage4d_c_time_dt00125_nelem2_20260811T063528Z_b309b67168`，`dt=0.00125 s`、`nElem=2`、200 步、物理时间 0.25 s。粗时间步直接读取 Stage 4D-B 100 步基准，未重新计算或覆盖基准。细步每两个 step 与粗步在 `0.0025, ..., 0.25 s` 逐点对齐，共 100 个共同时间点，没有插值掩盖时间错位。

细步运行完成，最大 CFL 为 `0.086281397650671`。力、位移峰值、位移 RMS、速度 RMS、平均阻力、横向力 RMS、累计 `abs(W_CFD)` 和两组 `E_c` 均满足各自阈值；但结构全自由度状态比较未满足要求：

| 指标 | 结果 | 阈值 | 结论 |
|---|---:|---:|---|
| `q` 对齐 NRMSE | `6.7702107976008e-07` | `0.05` | 通过 |
| `qdot` 对齐 NRMSE | `0.3908521876924054` | `0.05` | 不通过 |
| `qddot` 对齐 NRMSE | `1.0941190222479935` | `0.05` | 不通过 |
| 粗步最大 CFL | `0.1725241657902625` | `<0.8` | 通过 |
| 细步最大 CFL | `0.086281397650671` | `<0.8` | 通过 |
| 粗步 `E_c` | `9.906678707660641e-05` | `≤0.10` | 通过 |
| 细步 `E_c` | `1.0344592190732707e-04` | `≤0.10` | 通过 |

因此时间步子 Gate 不通过。按照任务停止条件，未启动 nElem=4/8 结构收敛、严格 10+10 restart 或 1.0 s 分级延时重型计算。失败证据和细步完整运行目录均保留。

## 证据文件

- `results/07_stage4d_c_convergence/template_audit.json`
- `results/07_stage4d_c_convergence/baseline_audit.json`
- `results/07_stage4d_c_convergence/time_step_convergence.json`
- `results/07_stage4d_c_convergence/stage4d_c_time_dt00125_nelem2_20260811T063528Z_b309b67168/`

本报告不作长时间 VIV、锁定区或稳定振幅结论。
