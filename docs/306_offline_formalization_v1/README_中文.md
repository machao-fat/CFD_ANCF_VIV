# Stage306 三切片稳定响应离线正式化

本阶段仅以只读方式审计 Stage304 与 Stage305 已有证据，不启动 MATLAB、OpenFOAM、WSL、CFD 或 C++ worker，也不修改 ANCF/EB 核心、物理参数、`dt=0.005 s`、三切片配置、数值阈值或正式 0.2.1 协议。

审计命令：

```powershell
cd "D:\研二文件\开题准备\CFD_ANCF_VIV"
$env:PYTHONPATH = "$PWD\src"
python -m compileall -q "src\coupling\stage306_offline_formalization_v1" "tools\stage306_offline_formalization_v1" "tests\stage306_offline_formalization_v1"
python -m unittest discover -s "tests\stage306_offline_formalization_v1" -p "test_*.py" -v
python "tools\stage306_offline_formalization_v1\run_offline_formalization.py" --compileall-pass --tests-pass --test-count 11
```

输出位于 `results/306_offline_formalization_v1`。工具拒绝覆盖已有 Stage306 结果；重复审计时应指定新的空输出目录。Stage304/305 证据始终只读。

正式化采用末 15 个完整周期，并按 5+5+5 个周期组成三个相邻窗口，复核频率、RMS、峰峰值、均值偏移及 FFT/峰值频率一致性。OpenFOAM 原始日志补充 CFL 与瞬时全局连续性误差的覆盖和有限值证明；沿用既有 `CFL < 0.8` 硬门槛，不为连续性误差新增阈值。

方法顺序建议是先做切片数量收敛，再做公开试验验证。但在真实 5 切片计算之前，必须先解释或排除 Stage305 三个 slice 的 force hash 全程一致现象，并通过短窗口 slice-specific motion/force smoke。切片数研究先比较 3 与 5；只有 3→5 趋势仍未收敛时才申请 9 切片，避免无依据地扩大计算量。

## 正式化结果

`STAGE4F_D_THREE_SLICE_STABLE_RESPONSE_OFFLINE_FORMALIZATION_V1_GATE: pass`

- Stage304 终点与 Stage305 起点均为 `global_step=16000,time=80 s`，worker、fixture、participant 及 Stage304 final-state hash 全部连续。
- Stage305 完成至 `global_step=50000,time=250 s`；34,000 个 mapping 记录、340 个 checkpoint、三个 slice barrier 和 return code 全部一致，owned residual 为 0。
- 末 15 个完整周期覆盖 `156.40–248.85 s`。峰值法频率为 `0.1622498648 Hz`，FFT 为 `0.1621621622 Hz`，相对差 `0.0541%`。
- 三个相邻五周期窗口的频率漂移 `0.1621%`、RMS 漂移 `0.1150%`、峰峰值漂移 `0.0217%`、均值跨度/平均 RMS `0.2443%`，均低于沿用的 `5%` 稳定阈值。
- 三个 slice 各有 34,001 条 Courant 记录及 510,000 条连续性记录；最大 CFL `0.613734 < 0.8`，最大瞬时全局连续性误差绝对值 `1.47432e-13`，所有值有限。
- 最大虚功、合力、力矩误差分别为 `4.28899e-14`、`1.31172e-16`、`3.05142e-13`。
- Stage306 真实进程启动数：MATLAB=0、OpenFOAM=0、WSL=0、CFD=0、C++ worker=0。

因此，本算例的响应频率与晚期三切片稳定响应可以正式标记为 `completed_for_this_three_slice_case`。这不等于完成 Strouhal、锁定区、切片数量收敛或公开试验验证；这些状态继续保持 `not_completed`。

## 下一阶段选择

优先做切片数量收敛，原因是当前只证明了一个三切片离散配置随时间稳定，尚未证明它对轴向切片离散不敏感。若直接比较公开试验，数值与试验的差异会同时包含切片数误差、模型形式误差、边界/参数误差和试验不确定度，无法判断误差来源。冻结合理的切片配置后再验证公开试验，结论才可解释、可复现，也更适合作为论文证据链。

成本控制采用分级策略：先离线冻结 3/5 切片的相同物理合同和比较指标，再做短窗口五切片身份 smoke；smoke 必须证明每个 slice 获得自己的位移、速度、载荷和 ack。通过后只申请 3 对 5 的正式比较；仅当 3→5 的趋势仍不能满足既有收敛合同，才考虑 9 切片。任何真实运行仍需新的明确授权。
