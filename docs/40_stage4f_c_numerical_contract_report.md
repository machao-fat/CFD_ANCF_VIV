# Revised numerical timestep contract

最终时间步合同为：`0.00125 s` 候选生产 baseline，`0.000625 s` verification，`0.0025 s` rejected coarse timestep。窗口 `1.5075 -> 1.5575 s`、三 slice、Stage 23 exact tau、5% 门槛、1e-11 restart 门槛及全部物理/数值门槛保持不变。修订淘汰证据不足的粗步长，不是放宽门槛。
