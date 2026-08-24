# Stage95 Performance Optimization V2

This isolated stage contains benchmark contracts, real timing ingestion, and attribution only. It does not modify ANCF/EB, physics parameters, global dt, the three-slice contract, numerical thresholds, formal 0.2.1 semantics, or any Stage1-94 evidence/runtime.

The only permitted real benchmark is a fresh stage/run/case/runtime using source step 559, exactly 40 steps, 0.05 s, and three slices. MATLAB must be owned by the user's Administrator Console SessionId=1 runner. Codex must not launch MATLAB, OpenFOAM, WSL, or CFD and must not fall back to per-step `matlab -batch`.

Offline checks:

```powershell
cd "D:\研二文件\开题准备\CFD_ANCF_VIV"
$env:PYTHONPATH = ".\src"
python -m compileall -q .\src\coupling\performance_optimization_v2 .\tools\performance_optimization_v2
python -m unittest discover -s .\tests\performance_optimization_v2 -v
```

After the user-session runner has produced independent B/M/O/P/I/A/combination measurements, run:

```powershell
python .\tools\performance_optimization_v2\audit_benchmark.py --input .\results\95_performance_optimization_v2\real_measurements.json --out-dir .\results\95_performance_optimization_v2
```

The auditor is read-only with respect to external processes. Missing real evidence, incomplete 40-step traces, nonzero return codes, identity errors, nonzero residuals, repeatability over 10%, or failure to reach 1.5x/600 s produces `do_not_pass`.

Stage95 runner commands (only from the user's interactive Console SessionId=1):

```powershell
cd "D:\研二文件\开题准备\CFD_ANCF_VIV"
powershell -ExecutionPolicy Bypass -File ".\tools\performance_optimization_v2\start_performance_benchmark_runner.ps1"
powershell -ExecutionPolicy Bypass -File ".\tools\performance_optimization_v2\get_performance_benchmark_runner_status.ps1"
```

The runner accepts the MATLAB-persistent (`M`) worker directly, or an explicit hash-bound `coordinator_command` for `O`/`P`/combined configurations. Without that command, those factors are rejected fail-closed. It never falls back to the old per-step launcher.

The real coordinator entry point is `coupling.performance_optimization_v2.real_coordinator`. It reuses the accepted Stage75 formal engine and stabilizer, stages only the manifest-listed source checkpoint files into a fresh runtime, and enables persistent MATLAB/OpenFOAM or parallel slices only when the contract explicitly contains those factors. A contract can be prepared from the user's PowerShell session as follows (use a new runtime and output path for every configuration):

```powershell
$source = "D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\stage4f_d_e5_b_bounded_campaign_attempt3\block_3\checkpoints\checkpoint_step00000559_22277fd2c60d.json"
$runtime = "D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\performance_optimization_v2\benchmarks\MOPIA_001"
$out = "D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\performance_optimization_v2\inbox\MOPIA_001_contract.json"
python .\tools\performance_optimization_v2\write_benchmark_contract.py `
  --label "M+O+P+I+A" `
  --source-checkpoint $source --source-step 559 --source-time 2.2075 --source-tick 2207500000 `
  --runtime $runtime --out $out `
  --coordinator-command python -m coupling.performance_optimization_v2.real_coordinator
```

`B` is the measured old per-step baseline; `M`, `O`, and `P` independently select persistent MATLAB, persistent OpenFOAM, and optional parallel slice calls. `I` and `A` are recorded as explicit contract factors and are never inferred from mock timing. The coordinator validates the source SHA, uses exactly 40 steps/0.05 s/three slices, and writes `benchmark_result.json` plus per-step telemetry. It never starts another configuration automatically.

每个配置完成后，将其结果加入独立矩阵（重复测量同一 label 会追加样本）：

```powershell
python .\tools\performance_optimization_v2\collect_benchmark_result.py `
  --result "$runtime\benchmark_result.json" `
  --input ".\results\95_performance_optimization_v2\real_measurements.json"
```

收集完 B、M、O、P、I、A、组合配置和至少两次 FINAL 后，再运行前文的 `audit_benchmark.py`。任何失败结果都不会被收集脚本接受。

Stop only with:

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\performance_optimization_v2\stop_performance_benchmark_runner.ps1"
```
