# Stage 299：低体积收敛可观测性审计

本阶段只读取 Stage 294、295、297、298 的既有力时序，不启动 MATLAB、OpenFOAM、WSL 或 CFD，也不修改任何旧证据。

## 结论

现有 `0–125 s` 数据可以复核：

- 标量力样本数量；
- 峰值、周期和初步频率；
- 三个统计窗口的均值、RMS、峰峰值和幅值漂移；
- 三个 slice 的同步/一致性（由既有 barrier 和力记录支持）。

现有 Stage 298 没有保留足够的 OpenFOAM stdout，因此不能从旧 runtime 证明每一步的 PIMPLE 残差、Courant 数和质量守恒；也没有保存虚功、合力/力矩误差的逐窗口摘要。这些指标必须在下一次运行中以标量摘要形式记录。

## 下一次运行的低存储记录

1. 每 `0.05 s` 写一行 `force_observables.jsonl`：时间、tick、三个 slice 合力、均值、RMS 输入和 payload hash。
2. 每 100 个 global step 写一行 `worker_quality.jsonl`：worker residual/iterations、`q/qdot` 范数、有限值计数和返回码。
3. 每个 CFD 时间步写一行 `openfoam_quality.jsonl`：最大残差、最大 Courant、continuity global、迭代次数；不保留完整 stdout。
4. 每个接受的峰值/周期写一行 `cycle_events.jsonl`，并在段末写三窗口摘要和 FFT/过零频率差异。
5. 继续 `purgeWrite=1`，只保留源场、最新场、最终 restart 和上述标量证据。

这些记录总量通常只有数百 KB 到数 MB，不会复制完整 CFD 场。任何缺失、非有限、身份不一致或 solver 非零返回仍然 fail-closed。

## 下一次运行的调用接口

结构 participant 在原有参数后增加：

```text
--convergence-log <runtime>/logs/convergence_summary.json
```

每个 OpenFOAM slice 使用质量日志包装器：

```text
python3 tools/convergence_observability_v1/run_openfoam_with_metrics.py \
  --metrics <runtime>/logs/openfoam_0000_quality.json \
  --failure-tail <runtime>/logs/openfoam_0000_failure_tail.txt \
  -- pimpleFoam
```

三个 slice 分别写入 `openfoam_0000_quality.json`、`openfoam_0001_quality.json` 和 `openfoam_0002_quality.json`。launcher 必须检查包装器返回码和三份质量摘要的时间覆盖；任何一份缺失都使该 run fail-closed。旧 Stage 298 不重跑、不补写这些文件。
