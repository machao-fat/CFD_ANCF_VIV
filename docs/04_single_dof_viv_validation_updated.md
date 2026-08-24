# Re=100 单自由度自由 VIV 补算

## 参数与边界

当前采用 `rho=1000 kg/m^3`、`D=1 m`、`U=1 m/s`、`Re=100`、`m*=10`、`zeta=0.01`。质量比定义为

`m*=m/(rho*pi*D^2/4)`，

约化速度定义为 `Ur=U/(fn D)`，故 `fn=1/Ur Hz`。结构只允许横流一自由度，保持非零初扰动 `y0=0.001D`。这与 Tang et al.（DOI [10.1155/2013/890423](https://doi.org/10.1155/2013/890423)）作为趋势参照时必须明确区分：该参照是二维自由度问题，本项目当前是横流 1DOF，不能宣称复现其二维振幅。

## 已运行筛查

Ur=5.2 使用固定圆柱 `t=30 s` 发展流场作为初始 `U/p`，固定启动 2 s 后释放，`dt=0.0025 s`，运行到 10 s：

| 指标 | 结果 |
|---|---:|
| 稳定候选窗口 | 5–10 s |
| 结构周期数 | 0.96（不足 10 周期） |
| `A/D` RMS | 0.0472 |
| `A/D` 峰值 | 0.0949 |
| 响应/升力主频 | 0.210 Hz |
| `f/fn` | 1.09 |
| 窗口平均流体功 | 15.65 W |
| 窗口流体功 | 78.31 J |
| 窗口阻尼耗散 | 3.57 J |
| 最大预测位移残差 | `4.13e-10 m` |

该筛查证明释放后存在非零响应并接近同步区，但不满足稳定窗口准入。Ur=5.2 的 60 s、约 11.5 周期长算例已启动，结果写入 `results/04_sdof_viv_campaign/Ur5p2_long`，完成前不把该工况标为通过。

## 统计规则

分析器 `tests/sdof/analyze_campaign.py` 对去瞬态窗口去均值/去趋势，报告窗口长度和频率分辨率，同时用 FFT、零交叉和峰值周期交叉检查。最终 campaign 需覆盖 Ur=4.0、5.2、6.0、7.1、8.0，并且每个工况至少 10 个稳定结构周期，另做 dt/2。

## 当前判断

SDOF 物理准入：未通过。原因是五点曲线和稳定窗口尚未齐全，而不是把单个短窗的非零响应解释成锁定趋势。
## Latest remediation result (2026-08-04)

The Re=100, m*=10, zeta=0.01 transverse 1DOF campaign was screened without claiming a lock-in result. Ur=5.2 reached 18 s and was stopped at about 1.73 structural cycles because the response was not statistically stationary; Ur=6.0 reached only 0.83 cycles. The 10 s Ur=5.2 screen gave A/D RMS 0.04718, peak 0.09491, f/fn 1.0915, and mean power 15.65 W.

The valid same-initial-flow dt/2 comparison changed displacement RMS by 6.25%, force RMS by 16.03%, and mean power by 31.64% over a window of only 0.96 cycles. The five-point Ur curve and ten stable cycles per point remain incomplete. See `results/04_sdof_viv_campaign/sdof_campaign_summary.json`.
