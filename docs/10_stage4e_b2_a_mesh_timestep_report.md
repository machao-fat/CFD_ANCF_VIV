# Stage 4E-B2-A 网格、时间步与边界/来源审计

## 范围与来源

本审计针对 `20260814T051204411Z_stage4e_b2_a_retry3` 的新建案例；没有修改旧固定圆柱、Stage 4D、Stage 4E-A/B1、正式0.2.1协议或ANCF生产代码。所有案例位于唯一run_id目录，日志和request/response类运行文件位于D盘runtime根目录。

## 可重复性

父路线G flow profile SHA-256：`28238a9623a07dd5e8f6e940678377f0a9975035236749c0dbf7a916e1dfd90e`；父manifest：`995e2cd958dda81ea00574187a7b189785f28d54266839debd11976bcd3a7860`；父config：`fd847246d3e0ed00ec49d3a53644bd32651d6e185ac0cb7c33f91a8da056e677`。案例字典hash、checkMesh日志hash、solver日志hash和force history均由结果JSON指向或可从新案例复算；物理身份hash不含绝对路径。

## 网格审计

`mesh_family.json`给出每个完成网格的points/faces/cells、圆周单元、第一层高度和径向层数；所有已运行网格的checkMesh为 Mesh OK。fine案例的CFL失败不是通过降低阈值消除的。

## 运行和统计审计

OpenFOAM-10由WSL `/opt/openfoam10/etc/bashrc`提供；pimpleFoam的每一步记录CFL，forceCoeffs使用全局 `(1,0,0)` dragDir、`(0,1,0)` liftDir、`rhoInf=1000`、`lRef=D`、`Aref=D*1m`。没有局部载荷旋转。所有已完成solver日志返回0并含End，但fine案例最大CFL=0.9920，触发安全停止。

正式统计窗口包含三窗口相对变化、Cd均值/RMS、Cl RMS、峰峰值、FFT主频、零交叉频率和St；由于有效周期/窗口稳定性不足，不将它们升级为物理验证或实验结论。

## 进程和卫生

本任务使用ProcessLimiter的最大并发2，实际solver并发峰值为1；已登记PID、父PID、创建时间、命令、用途、日志和关闭方法。任务结束时只清理已登记任务进程，并关闭本任务启动的WSL计算环境；不按名称批量终止未知进程。D盘运行时卫生结果见 `runtime_path_audit.json`、`process_inventory_before.json`、`process_inventory_after.json`、`c_drive_write_diff.json`。

## 结论

网格和求解器可以完成有限短时pilot，但本次证据不满足正式模型/网格/时间步Gate。推荐保留失败fine案例，下一次独立run应在未降低CFL阈值的前提下重新设计fine时间步/网格并从新鲜案例开始；本次不进入真实九切片。
