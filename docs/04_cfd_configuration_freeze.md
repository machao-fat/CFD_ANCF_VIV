# 阶段三 CFD 配置冻结

严格在线等价和单切片结构闭环采用 expanded 基线；本轮 SDOF 筛查沿用阶段二的 reduced medium 基线，二者不能混称为同一 CFD 配置。

| 项目 | 冻结值 |
|---|---|
| OpenFOAM | Foundation OpenFOAM 10，build `10-c4cf895ad8fa` |
| 求解器 | `pimpleFoam`，层流 Stokes，应力模型不切换 |
| 圆柱/流体 | `D=1 m`，`U=1 m/s`，`rho=1000 kg/m^3`，`nu=0.01 m^2/s`，`Re=100` |
| 计算域 | expanded：上游 `10D`、下游 `20D`、上下 `15D`，二维厚度 `Lz=1 m` |
| 网格 | expanded medium，`16244` cells；fine 只作敏感性复核 |
| 时间格式 | `ddt=backward`，`div(phi,U)=Gauss linear` |
| CFD时间步 | `dt=0.0025 s`；敏感性使用 `0.00125 s` |
| 动网格 | `interpolatingSolidBody`，`innerDistance=0.75D`，`outerDistance=2.5D` |
| 在线运动 | `ancfFileMotion`，逐步 CSV + ready marker，不预加载整张运动表 |
| CFL阈值 | `maxCo < 0.30`；超限停止并保留日志 |
| 网格阈值 | `min determinant > 0.30`、`min volume > 0`、`max skewness < 0.70`、`max non-orthogonality < 45 deg` |
| 统计窗口 | 规定运动至少 10 个完整周期；自由 VIV 先固定结构达到 Cd/Cl 统计稳定，再统计至少 10 个响应周期 |
| 输出 | 每步压力力、黏性力、总力、CFL、网格指标、运动摘要、载荷 SHA-256、耗时 |

二维 `checkMesh` 可能额外输出 non-aligned edge 诊断；该项单独记录，不用删除或改阈值掩盖。只要核心几何指标和正体积条件满足，才可进入连续计算；若 determinant、体积、skewness 或 CFL 越界，立即停止。

## SDOF 筛查的配置差异

`results/04_sdof_viv_campaign/*` 当前使用 `fixed_cylinder_study_full30b/medium_dt0p0025/30` 的发展场和 `3268` cells、域 `(-5,-5,0)–(10,5,1)` 的 reduced medium 网格；它用于 Re=100 耦合框架筛查，不是 expanded 16244-cell 基准的替代。Ur=5.2/6.0 的非零响应因此只能作为接口和趋势筛查，不能直接作为最终公开基准锁定曲线。若要正式通过 SDOF 物理准入，必须在 expanded 配置上重新发展固定流场或给出独立的域无关性证据。
