# Stage 4E-A-v3.1 幅值语义与滤波稳健性报告

本报告是 v3 的定向离线小修。没有启动 OpenFOAM、pimpleFoam、checkMesh 或 setFields，也没有改写 v3 结果或原始 CSV。

## 来源与处理协议

公开来源 pin 为 commit `fe251f958ddf2f083b53cdb53a9d2addde85e17e`。该提交对应 `main1.m` 的历史记录；源文件和 CSV 均在内存/临时下载路径中校验，CSV 未写入项目。CSV SHA-256 为 `507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df`，`main1.m` SHA-256 为 `a2ab54340f2269afad1249d8c99b26b1e5aab2cd1691786c2c428dda64d0c963`。

v3.1 重算六种方案：去趋势、二阶 0.01–20 Hz、四阶 0.01–20 Hz、六阶 0.01–20 Hz、四阶 0.05–20 Hz、四阶 0.10–15 Hz。相对跨度定义为 `(max-min)/mean`，与 v3 已报告的稳健性口径一致。

## 幅值语义

结果中分别保存：

- `max_span_rms_m` 与 `max_span_rms_over_D`：沿程各点时间 RMS 的最大值；
- `max_instantaneous_peak_abs_m` 与 `max_instantaneous_peak_abs_over_D`：沿程和时间上的瞬时绝对峰值；
- `rms_peak_location_m` 与 `instantaneous_peak_location_m`；
- `amplitude_definition`。

名义四阶 0.01–20 Hz 结果为：

| 分量 | max span RMS/D | instantaneous peak/D | RMS峰位置 m | 瞬时峰位置 m |
|---|---:|---:|---:|---:|
| CF | 0.2451494374 | 0.6456139648 | 3.8200 | 4.0492 |
| IL | 0.0544796431 | 0.2279678020 | 2.5976 | 1.9482 |

论文 RMS 曲线只能与 `max_span_rms_over_D` 比较，不能用含义模糊的 `max_A_over_D` 替代。

## 滤波分类

六方案相对跨度如下：

| 目标 | 频率 | q RMS | max span RMS/D | 瞬时峰值/D |
|---|---:|---:|---:|---:|
| CF mode 1 | 0% | 1.4495% | 1.1426% | 9.1615% |
| IL mode 2 | 0% | 22.0637% | 19.2810% | 20.2067% |
| IL mode 4 | 0% | 2.5106% | 19.2810% | 20.2067% |

五种带通方案之间：

| 目标 | 频率 | q RMS | max span RMS/D | 瞬时峰值/D |
|---|---:|---:|---:|---:|
| CF mode 1 | 0% | 0.2057% | 0.1446% | 1.7417% |
| IL mode 2 | 0% | **11.6485%** | 7.6362% | 3.6809% |
| IL mode 4 | 0% | 0.9231% | 7.6362% | 3.6809% |

因此：频率和模态身份可用于验证；CF mode 1 与 IL mode 4 的 q RMS 对滤波稳健；IL mode 2 的五种带通 q RMS 跨度约 11.65%，必须标记 `not_strict_amplitude`，不能作为严格幅值验收指标。不能删除不利方案。

四阶 0.01–20 Hz 继续作为名义项目处理协议，但所有名义幅值必须带协议标签和不确定性范围；这不是作者 `bpass.m` 的严格复现。

## 结论边界

本报告支持频率/模态验证和明确的幅值不确定性分类，不支持 IL mode 2 严格幅值验证，不构成五切片 CFD 或 VIV 锁定区结论。
