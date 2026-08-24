# Stage 4F-C C 分支 dt/2 验收报告

Gate：`STAGE4F_C_DT2_VALIDATION_V1_GATE: do_not_pass`。

C 从同一父 checkpoint 全新启动，dt=`0.00125 s`，完成 40/40 global steps，时间 `1.5075 -> 1.5575 s`。三 slice、MATLAB correct、solver、不可变 consumed-force snapshot、checkpoint lineage 和逐步冻结硬门槛均通过。C 共生成 40 个 unified checkpoint 和 120 个 force snapshots。

失败原因是运行前冻结的 A/C dt/2 comparison contract，而非单步数值硬门槛：raw y 总力冲量归一化差异=`0.1372846120476647 > 0.05`。raw x=`0.04760706095748545`；applied x=`0.15065162395474285`，applied y=`0.14869442136392244`。该合同失败后停止，不重试 C，不进入五/九切片、长时 VIV、锁定区或实验验证。

最大 CFL=`0.06819895002072694`，raw `|Cd|`=`4.251335917407953`，速度一致性=`0.0002937739527373135`，虚功=`4.768380515474943e-16`，力转换=`0`，几何误差=`8.326672684688674e-17 m`。父 checkpoint 和 A/B 旧证据保持只读未变。
