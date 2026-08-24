# OpenFOAM 10 环境冻结记录

记录日期：2026-08-03

## 1. 运行环境

| 项目 | 冻结值 |
|---|---|
| 主机 | Windows（Codex PowerShell 工作区） |
| Linux 运行层 | WSL2 |
| 发行版 | Ubuntu-22.04、WSL 2 |
| OpenFOAM | OpenFOAM Foundation 10，安装目录 `/opt/openfoam10` |
| 编译器 | GCC 11.4.0，WSL2 `/usr/bin/g++` |
| 构建选项 | `linux64GccDPInt32Opt`，双精度、32-bit label |
| 固定圆柱求解器 | `icoFoam` |
| 物性文件 | OpenFOAM 10 的 `constant/physicalProperties` |
| 运行命令 | `source /opt/openfoam10/etc/bashrc; blockMesh; icoFoam` |

OpenFOAM 10 官方发布说明明确记载了 Ubuntu/WSL 安装路径、C++14/GCC 支持以及从 v10 起物性集中到 `physicalProperties` 的变化：[OpenFOAM 10 release notes](https://openfoam.org/release/10/)。本项目不混用其他发行版或版本的案例字典。

## 2. 复现命令

在 PowerShell 中，从项目根目录运行：

```powershell
wsl.exe bash -lc 'source /opt/openfoam10/etc/bashrc; cd /mnt/d/研二文件/开题准备/CFD_ANCF_VIV/cases/openfoam/fixed_cylinder; ./Allrun'
```

也可直接调用：

```powershell
wsl.exe bash -lc 'source /opt/openfoam10/etc/bashrc; cd /mnt/d/研二文件/开题准备/CFD_ANCF_VIV/cases/openfoam/fixed_cylinder; blockMesh | tee log.blockMesh; icoFoam | tee log.icoFoam'
```

`Allrun` 默认先清理生成的网格/时间目录，再执行 `blockMesh`、`checkMesh` 和 `icoFoam`，最后调用 Python 后处理脚本。原始字典和脚本不会被运行覆盖。

## 3. 版本相关注意事项

- v10 使用 `constant/physicalProperties`，本案例不使用旧版本 `transportProperties`。
- OpenFOAM 10 文档中 `forceCoeffs` 是 `forces` 的扩展，提供升力、阻力和力矩系数；本案例同步记录原始压力/黏性力，避免只保留无量纲系数。[forceCoeffs class reference](https://cpp.openfoam.org/v4/classFoam_1_1functionObjects_1_1forceCoeffs.html)
- 固定圆柱不需要动态网格；规定运动阶段另建 ALE/动网格案例，不在本目录中假定 `icoFoam` 可直接移动网格。

## 4. Gmsh 网格工具

已核对 Windows Gmsh：

```text
版本：4.14.1
程序：D:\Gmsh\gmsh-4.14.1-Windows64\gmsh-4.14.1-Windows64\gmsh.exe
```

OpenFOAM 10 的 `gmshToFoam` 也已确认可用。后续 coarse/medium/fine 网格研究将把 Gmsh 网格放在独立子目录中，先用 Gmsh 生成 `.msh`，再由 WSL 的 `gmshToFoam` 转换并执行 `checkMesh`。当前已经跑通的 `blockMesh` 基线不覆盖。
