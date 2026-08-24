# OpenFOAM 10 固定二维圆柱首个案例

这是阶段二任务 1 的 blockMesh 基线案例；最终 Gmsh 敏感性结果位于项目的 `results/03_fixed_cylinder/sensitivity_full30b/`。

## 工况

```text
D       = 1 m
U_inf   = 1 m/s
rho     = 1000 kg/m^3
nu      = 0.01 m^2/s
Re      = U_inf*D/nu = 100
L_z     = 1 m
solver  = icoFoam (OpenFOAM Foundation 10)
dt      = 0.0025 s
t_end   = 30 s
```

`0.orig/` 保存未被 `setFields` 修改的初始场，`Allrun` 会在每次运行前恢复它。`system/setFieldsDict` applies a recorded asymmetric startup seed
`Uy/U_inf=0.1` only in a short downstream box `(0.5D<x<2D,
|y|<0.4D)`. The inlet and upper/lower symmetry conditions remain unmodified;
the seed is a numerical trigger, not a physical cross-flow boundary condition.

几何是八扇区贴体圆柱网格，圆柱半径 `0.5D`，近场环半径 `0.8D`，入口/上游、出口/下游和上下边界约为 `5D/10D/5D`。前后面由 `defaultFaces` 设为 `empty`，代表二维场的单位展向厚度 `L_z=1 m`。中等网格的最小面插值权重约为 `0.0315`，`system/meshQualityDict` 将项目阈值固定为 `0.03`；该数值会写入网格检查记录，不能把阈值放宽后不报告。

## 运行

```powershell
wsl.exe bash -lc 'source /opt/openfoam10/etc/bashrc; cd /mnt/d/研二文件/开题准备/CFD_ANCF_VIV/cases/openfoam/fixed_cylinder; ./Allrun'
```

运行输出：

- `log.blockMesh`：网格生成；
- `log.checkMesh`：网格质量和边界检查；
- `log.icoFoam`：残差、Courant 数和时间推进；
- `postProcessing/cylinderForces/`：压力力、黏性力和力矩；
- `postProcessing/cylinderForceCoeffs/`：阻力、升力和力矩系数；
- `results/03_fixed_cylinder/medium/`：后处理 CSV、PNG 和摘要 JSON。

Gmsh 三档网格生成与转换入口（PowerShell）：

    .\mesh\gmsh\generate_meshes.ps1
    .\mesh\gmsh\prepare_study_cases.ps1 -StudyRoot ..\fixed_cylinder_study_full30b
    wsl.exe bash -lc 'bash /mnt/d/研二文件/开题准备/CFD_ANCF_VIV/cases/openfoam/fixed_cylinder/mesh/gmsh/convert_study_cases.sh /mnt/d/研二文件/开题准备/CFD_ANCF_VIV/cases/openfoam/fixed_cylinder_study_full30b'

生成尾流瞬态图（需先完成求解并生成最新时刻的 VTK）：

```powershell
wsl.exe bash -lc 'source /opt/openfoam10/etc/bashrc; cd /mnt/d/研二文件/开题准备/CFD_ANCF_VIV/cases/openfoam/fixed_cylinder; postProcess -func vorticity -latestTime -noFunctionObjects; foamToVTK -latestTime -fields "(U vorticity)"; PYTHONPATH=/opt/paraviewopenfoam510/lib/python3.10/site-packages /opt/paraviewopenfoam510/bin/pvpython scripts/render_vortex.py --vtk VTK/fixed_cylinder_12000.vtk --output /mnt/d/研二文件/开题准备/CFD_ANCF_VIV/results/03_fixed_cylinder/medium/vorticity_t30.png'
```

OpenFOAM 的 `forces` 对本案例的有限厚度 `L_z=1 m` 积分，因此原始力是 N；它也等于单位展向力的数值。耦合给真实切片时只使用一次 `F_slice=f_2D*l_slice`，本固定圆柱结果不要重复乘长度。

## 预期趋势

该工况应出现 Re=100 的二维交替脱涡。无界圆柱文献的目标量级为 `Cd_mean≈1.33–1.40`、`St≈0.16–0.17`、升力主幅值约 `0.30–0.34`。首轮运行结果只有在完成后处理、网格质量检查和边界条件核对后才写入阶段二准入报告。
