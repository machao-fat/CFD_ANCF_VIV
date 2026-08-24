# movingWall 运动边界烟测

## 配置

OpenFOAM 10 `pimpleFoam`，二维圆柱，`interpolatingSolidBody`，`innerDistance=0.75D`，`outerDistance=2.50D`，`D=1 m`，`U=1 m/s`，`dt=0.0025 s`，运动边界为 `movingWallVelocity`。固定圆柱和规定正弦运动分别运行 200 步至 0.5 s。

## 结果

| 案例 | CFL 最大值 | 力样本 | 最大 `|y|` | 最小体积 | 最大 skewness | 结论 |
|---|---:|---:|---:|---:|---:|---|
| fixed | 0.12905212 | 201 | 0 | 0.0015248081 | 0.4505133 | 计算通过 |
| prescribed | 0.13253225 | 201 | 0.04817537 m | 0.0015248081 | 0.4505133 | 计算通过，保留二维诊断 |

两案例均无 NaN/Inf，pimpleFoam 正常结束。规定运动案例标准 `checkMesh` 返回 `Failed 1 mesh checks`，具体为二维非空方向 edge-alignment 诊断；同时体积、非正体积、skewness、non-orthogonality 和 CFL 均满足冻结配置中的核心阈值。因此本报告将其记为“几何质量条件通过”，不改写为 clean `checkMesh`。

结果文件：`results/04_moving_wall_smoke/moving_wall_smoke_summary.json`。该烟测只证明 movingWall 能工作，不证明自由 VIV 的长期稳定性。
