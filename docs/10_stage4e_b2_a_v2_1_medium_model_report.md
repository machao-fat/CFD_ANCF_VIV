# Stage 4E-B2-A-v2.1：最大 Re medium 模型筛查报告

## 冻结输入

`D=0.02841 m`，`U=0.43414375179615955 m/s`，`Re=12334.023988528894`，`dt=0.0004 s`，baseline medium 网格，二维挤出厚度和力归一化合同沿用 v2 已验收结果。上游九切片身份和正式 0.2.1 协议 hash 未改变。

## laminar

laminar 暖机和 4 个生产 block 均完成至 10.5 s，生产最大 CFL 为 0.4624675993248588。将 4 个生产 block 的 raw `forces.dat` 按物理时间合并并去除 restart 重复行后，共 5151 行；未只取最后一个 block。

正式统计窗口为 3.288518089383598–10.498518089388352 s，共 15.995562950650134 个有效周期。结果为：

- mean Cd = 1.0416920695834482
- Cd fluctuation RMS = 0.02844421662682312
- Cl fluctuation RMS = 0.5167387047877067
- Cl peak-to-peak = 1.4821610771083797
- FFT = 2.2185246810873216 Hz
- zero-crossing = 2.266441506329098 Hz
- 一致性相对差 = 0.024062614837391638
- St = 0.1451783791173483

频率状态为 `evaluable_pass`；FFT 信噪比约 3.896×10^6。三个连续窗口均完成，mean Cd、Cd fluctuation RMS 和 Cl fluctuation RMS 的窗口变化在既定稳定性检查范围内。

## kOmegaSST

kOmegaSST 暖机和 4 个生产 block 均完成至 10.5 s，生产最大 CFL 为 0.4545301513663924。生产 raw force 同样为 5151 行。结果为：

- mean Cd = 0.9957010001759964
- Cd fluctuation RMS = 8.49723004824145×10^-7
- Cl fluctuation RMS = 4.26413021718743×10^-5
- Cl peak-to-peak = 9.01886508011312×10^-5
- frequency status = `not_evaluable_low_amplitude`
- dominant frequency、zero-crossing frequency、St = null

该结论来自冻结的绝对幅值门槛，不是把数值噪声解释为涡脱频率。SST 的五个评价点均有真实 `yPlus` volScalarField 和 `yPlus.dat` 原始文件。暖机结束的圆柱 patch min/mean/p95/max 为 `0.00616331838/0.02413528675/0.07837688121/0.11247356383`；最终 block 的对应值为 `0.00199288131/0.01035505648/0.03910080054/0.04146994817`。独立 field 统计与 OpenFOAM `yPlus.dat` 的 min/max/average 交叉误差不超过 `6.94e-18`，p95 明显满足 ≤1 的目标。laminar yPlus 记录为 not applicable。

## 模型决定

laminar 是当前 medium 筛查中唯一满足统计有效性的候选；SST 是稳定的近稳态、低升力拒绝候选。该结果不是网格、dt 或域收敛结论，也不是 VIV 试验幅值验证。正式 entry candidate 仍为 `not_ready_for_next_stage`，因为 I/O 磁盘缩减建议门槛未满足且后续收敛阶段尚未执行。
