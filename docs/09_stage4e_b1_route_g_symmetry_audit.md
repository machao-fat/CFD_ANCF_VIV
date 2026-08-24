# Stage 4E-B1 路线 G 对称性审计

- 镜像中心：圆柱中心 `[0.0, 0.0, 0.0]`；镜像公式 `x' = 2*x_cylinder - x`。
- 速度变换：`Q=diag(-1,1,1)`；正向 `U=(+1,0,0)`，反向 `U=(-1,0,0)`。
- 正向：left 速度入口、right 压力出口；反向：right 速度入口、left 压力出口。
- 圆柱保持 `noSlip`；上下边界相同 `symmetryPlane`；前后面 `empty`；forces 输出保持全局坐标且无额外旋转。
- 父 Stage 4E-A 文件未变：`True`。
- 结果摘要：`passed_with_scope_limits`。

Re=100 仅是边界与坐标对称性烟测，不外推至 VIVdatashare 的高 Re 物理模型适用性。
