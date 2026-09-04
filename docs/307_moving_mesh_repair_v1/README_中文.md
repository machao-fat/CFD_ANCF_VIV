# Stage307 动网格绑定修复离线前置

本阶段修复并证明了 OpenFOAM 动网格配置，但没有启动任何真实 MATLAB、OpenFOAM、WSL、CFD 或 C++ worker。

## 根因

原配置使用：

```text
namePointDisplacement unused;
nameCellDisplacement cellDisplacement;
```

而 `constant/dynamicMeshDict` 使用 `displacementLaplacian`。preCICE adapter 的 face-center 接收路径会先写 `cellDisplacement`，只有存在 `pointDisplacement` 时才调用 `faceToPointInterpolate`，将位移交给 OpenFOAM 动网格。因此原运行中结构位移没有进入网格点。

## 修正合同

新的每个 slice 配置固定为：

```text
namePointDisplacement pointDisplacement;
nameCellDisplacement cellDisplacement;
locations faceCenters;
patches (cyl);
```

并要求 `0/pointDisplacement` 的 `cyl` 为 `fixedValue`、`0/U` 的 `cyl` 为 `movingWallVelocity`、`dynamicMeshDict` 保持 `displacementLaplacian`。

## 离线命令

```powershell
cd "D:\研二文件\开题准备\CFD_ANCF_VIV"
$env:PYTHONPATH = "$PWD\src"
python -m compileall -q "src\coupling\stage307_moving_mesh_repair_v1" "tools\stage307_moving_mesh_repair_v1" "tests\stage307_moving_mesh_repair_v1"
python -m unittest discover -s "tests\stage307_moving_mesh_repair_v1" -p "test_*.py" -v
python "tools\stage307_moving_mesh_repair_v1\prepare_offline_preflight.py"
```

输出在 `results/307_moving_mesh_repair_v1`，修正配置模板在 `runtime/stage307_moving_mesh_repair_v1_preflight`。工具拒绝覆盖已有结果。

## 新计算前必须检查

短 smoke 中每一步必须保存：每个 slice 接收到的 displacement hash、`pointDisplacement` 圆柱边界非零值、移动网格点 hash、Force hash、step/time/tick/ack identity。若三个 slice 的运动不同而网格或 Force 被复制，必须立即 fail-closed。通过本 Gate 只代表具备申请短 prescribed-motion smoke 的资格，不代表已授权启动真实计算。
