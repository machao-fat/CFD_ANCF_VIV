# Stage 4D-A Sol正式验收

## 决定

Stage 4D-A于2026-08-11通过，但保留范围限制。批准进入Stage 4D-B的100步真实三切片CFD–ANCF中等步数工程稳定性、能量审计和10步连续/5+5 restart验证；不批准直接开展长时间自由VIV、锁定区或参数扫描。

## 复核证据

- 协议版本：`0.2.1`
- 三切片manifest：`d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`
- developed-flow bank：`5ed12fb1933d27baca9bc681ef21966341a93219cabd827c2a8225124c5cc8b7`
- Re80：315 s、31个有效周期、`St=0.1341705`、`Cl_rms=0.0396624`
- Re100：188.5 s、24个有效周期、`St=0.141500`
- Re120：139.5 s、22个有效周期、`St=0.148607`
- 三个流场的统计终点与实际快照时间误差均为0。
- Re80四段真实OpenFOAM日志均正常结束；259 s未通过，278、296.5、315 s连续三个实际评估点通过。
- ProcessLimiter真实峰值并发为2，区间重算峰值为2，无permit泄漏。
- 三个flow物理身份hash、场文件hash、力时程hash及bank hash均由Sol重算一致。
- v3专项测试：23/23通过。
- 全项目回归：223/223通过。
- `python -m compileall -q src tests`：通过。

## 范围边界

本验收只证明持久ANCF、受限OpenFOAM进程并发和三个充分发展二维切片初始场已满足中等步数耦合准入。尚未证明100步耦合稳定、真实耦合restart等价、耦合功缺陷合格、长期VIV统计平稳或锁定区预测有效。

## 下一门

Stage 4D-B必须使用v3 developed-flow bank初始化三个切片，将不同物理快照规范化到共同耦合时间原点，并使用持久ANCF runner和`max_processes=2`的ProcessLimiter。完成100步、能量审计和10步连续/5+5 restart后，才能再次申请长时间运行准入。
