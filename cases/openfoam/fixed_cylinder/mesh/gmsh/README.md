# Gmsh 网格生成入口

Gmsh 版本固定为 4.14.1：

    D:\Gmsh\gmsh-4.14.1-Windows64\gmsh-4.14.1-Windows64\gmsh.exe

在 PowerShell 中生成三档网格：

    .\generate_meshes.ps1

输出：

    generated/fixed_cylinder_coarse.msh
    generated/fixed_cylinder_medium.msh
    generated/fixed_cylinder_fine.msh

几何采用 D=1 m、上游 5D、下游 10D、横向 5D 和 z 向单位厚度。Gmsh 物理面分组为 front、back、lower、outlet、upper、inlet、cylinder；转换到 OpenFOAM 后必须再次核对边界名称和 empty 类型。
