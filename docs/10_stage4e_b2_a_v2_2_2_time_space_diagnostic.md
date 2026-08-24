# 时间—空间诊断

冻结比较方向为 `abs(a-b)/max(abs(b), epsilon)`，dt2 为 a、dt1 为 b；空间比较为 medium dt1 为 a、fine dt1 为 b。

- medium dt2→dt1：Cd fluctuation RMS=7.444324%（失败），mean Cd=1.420534%，St=0.876888%。
- fine dt2→dt1：所有冻结指标通过，Cd fluctuation RMS=4.986483%，St=1.694449%。
- medium dt1→fine dt1：空间比较失败，Cd fluctuation RMS=85.607013%，Cl fluctuation RMS=63.849365%。

因此 v2.2.1 medium→fine 差异不能归因于单一时间离散误差；至少存在二维 laminar 空间非收敛/模型—网格耦合敏感性。由于 medium 时间比较也失败，本轮不授权 conditional coarse dt1。
