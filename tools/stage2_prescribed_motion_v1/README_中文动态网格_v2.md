# Stage 2 Fluent 中文界面操作清单（v2）

## 目标与边界

这是单圆柱、外部规定横向运动的 Fluent 动态网格 smoke；不使用
ANCF 反馈、不使用 preCICE，也不修改主线三切片算例。参数固定为
`rho=1 kg/m3`、`mu=0.01 Pa s`、`U=1 m/s`、`D=1 m`、`Re=100`、
`A=0.1 m`、`f=0.16 Hz`、`dt=0.0025 s`。

本操作表针对 `v1` 在 `t=0.4725 s` 出现负体积后的修复。`v2` 保持
单一流体 cell zone：圆柱壁面作为刚体运动边界，`fluid-1` 作为变形
网格区，使用平滑和局部重构；不要创建共享节点的“内外刚体 cell zone”。

## 打开与读取

1. 在 `D:\CFD\stage2_prescribed_motion_v2\fluent` 启动 Fluent 3D、双精度、单核。
2. 读取 `stage2_openfoam.msh`。
3. 先执行“网格 -> 检查”，应能正常通过。

## 求解器、材料和边界

1. “常规”：压力基、瞬态。
2. “模型 -> 黏性”：层流。
3. `fluid-1` 指派 `water`；在“材料 -> water -> 编辑”确认：
   - 密度，常数，`1 kg/m3`；
   - 黏度，常数，`0.01 kg/(m s)`。
4. 边界：
   - `inlet`：速度入口，`(1,0,0) m/s`；
   - `outlet`：压力出口，表压 `0 Pa`；
   - `upper`、`lower`、`front`、`back`：对称；
   - `cylinder`：壁面。

## 动态网格（关键）

1. “定义 -> 动态网格”：启用动态网格。
2. 启用“平滑”，选择扩散型或弹簧型平滑。优先扩散型；其余参数保持默认。
3. 启用“局部重构/重网格（Remeshing）”，使用局部单元重构。起始阈值：
   - 最小长度尺度：`0.03 m`；
   - 最大长度尺度：`0.12 m`；
   - 最大单元偏斜度：`0.70`。
   这些阈值相对初始最小边长约 `0.052 m` 留有余量，用于避免单元翻转；
   它们是网格质量控制参数，不是物理或耦合参数。
4. 打开“动态网格区域/区域”，配置：
   - `fluid-1`：类型为“变形（Deforming）”，允许平滑和局部重构；
   - `cylinder`：类型为“刚体（Rigid Body）/指定刚体运动”；平移运动函数选
     `stage2_cylinder_motion`，不选择 6DOF、不设置转动。
5. “定义 -> 用户定义 -> 函数 -> 已编译”：加载目录中的 `stage2_udf`。
   函数列表应显示 `stage2_cylinder_motion`。

## 力报告、初始化与分段 smoke

1. 建立三个“报告定义”：Force X、Force Y、Moment Z；所有报告面仅选
   `cylinder`，并启用每时间步写文件。输出必须是 **Force**，不是
   Force Coefficient。已有 v1 的 `drag_force/lift_force` 数值就是实际力，
   不要把它们改为系数报告。
2. “求解 -> 初始化”：Hybrid 或标准初始化均可，初始 `x velocity=1`。
3. “运行计算”：时间步长 `0.0025 s`，每步最大迭代 `20`。
4. 运行 `5` 步。检查：无 `negative volume`、无 UDF 错误、三个报告各有
   5 个非空样本。
5. 不重新初始化，追加运行 `195` 步至 `t=0.5 s`。检查网格质量和残差。
6. 仅当 `t=0.5 s` 仍无负体积时，追加 `200` 步至 `t=1.0 s`。
7. 保存为 `stage2_fluent_v2_smoke.cas.h5` 和
   `stage2_fluent_v2_smoke.dat.h5`。

## 不通过时的处理

若仍有负体积，停止并保留日志；不要从失败状态继续。
首先将“最大长度尺度”从 `0.12 m` 降至 `0.10 m`，并将“最大单元偏斜度”
从 `0.70` 降至 `0.65` 后，从 `t=0` 重新做 5 步和 0.5 s smoke。不要改变
时间步、运动幅值、频率、流体参数或边界条件。

## 文件审计

运行结束后保留：`*.cas.h5`、`*.dat.h5`、三个 force report、
`stage2_fluent_motion_audit.csv` 和 Fluent transcript。完整流场可只保留
最终 case/data；不要保存每步场文件。

完成 1 s 后，在 PowerShell 运行：

```powershell
python "D:\研二文件\开题准备\CFD_ANCF_VIV\tools\stage2_prescribed_motion_v1\audit_fluent_smoke.py" `
  --fluent-root "D:\CFD\stage2_prescribed_motion_v2\fluent" `
  --output "D:\研二文件\开题准备\CFD_ANCF_VIV\results\stage2_prescribed_motion_v1\fluent_v2_smoke_audit.json"
```

只有脚本输出 `"status": "PASS"`，才把 Fluent 结果用于与 OpenFOAM 的载荷/相位对比。
