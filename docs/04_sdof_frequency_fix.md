# Ur=5.2 频率算法修复记录

## 修复内容

`tests/sdof/analyze_campaign.py` 中的零交叉频率原实现把正、负交替零交叉之间的两个间隔误当作半周期，并额外乘以 2。由于 `crossings[i+2]-crossings[i]` 已经跨越一个完整周期，现已改为：

```text
zero_crossing_frequency = 1 / mean(crossings[i+2] - crossings[i])
```

函数先去除常数和线性趋势，零交叉结果单独输出为 `zero_crossing_frequency`；频谱结果单独输出为 `DFT_frequency`。旧的 `*_fft` 字段只作为兼容别名，实际指向直接 DFT 结果，绝不再存放零交叉结果。

项目范围内检索后，确认同类二倍频公式只有上述一处；没有发现第二份独立实现。

## 自动化测试

`tests/sdof/test_frequency_algorithms.py` 覆盖以下信号：0.2 Hz 正弦、常数偏置、线性漂移和小幅确定性噪声。4/4 通过，频率误差均小于 1%，不再输出 0.4 Hz。与已有 `tests/sdof/test_compare_dt.py` 合并执行为 6/6 通过。

## Ur=5.2 重新分析

数据来自原有 0–60 s 分段，未重算旧段；窗口仍为 v3 的 8–34 s 和 34–60 s，但其含义重新标记为“启动增长窗口与后期窗口比较”。

| 窗口 | v3 旧值 | 修正零交叉频率 | DFT 频率 | `f/fn`（零交叉） |
|---|---:|---:|---:|---:|
| 8–34 s | 0.3628 Hz | 0.18091 Hz | 0.1811 Hz | 0.9407 |
| 34–60 s | 0.3763 Hz | 0.18778 Hz | 0.1870 Hz | 0.9764 |

`fn=0.1923077 Hz`。因此 v3 报告中的 0.36–0.38 Hz 是分析程序二倍频错误，旧绝对频率结论作废；窗口间相对频率变化百分比基本不受统一二倍频系数影响。修正后 Ur=5.2 的频率已接近固有频率，说明该工况接近锁定状态，但当时振幅和能量尚未稳定，不能只凭频率宣布稳态。

## 代码与证据

- 算法：[`analyze_campaign.py`](../tests/sdof/analyze_campaign.py)
- 单元测试：[`test_frequency_algorithms.py`](../tests/sdof/test_frequency_algorithms.py)
- 60 s 修正重分析：[`steady_metrics.json`](../results/04_sdof_corrected_campaign/Ur5p2_long/steady_metrics.json)
- 后期 112 s 审计：[`steady_metrics_v4.json`](../results/04_sdof_corrected_campaign/Ur5p2_extended/steady_metrics_v4.json)
