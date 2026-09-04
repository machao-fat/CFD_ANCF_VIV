# Stage308 三切片动网格 smoke

本阶段由用户明确授权，运行一个全新的三切片、8 步、`dt=0.005 s`、`0→0.04 s` moving-mesh smoke。它不是长时间 VIV，也不授权续算、E5-C、五/九切片或实验验证。

launcher 使用修正后的 `namePointDisplacement pointDisplacement`，并保留 `nameCellDisplacement cellDisplacement`。结束后必须同时证明：

- 三个 slice 的 `pointDisplacement` 圆柱边界存在且非零；
- OpenFOAM 实际写出移动网格点；
- 每步结构位移身份独立；
- 每步 Force hash 不被三个 slice 广播复制；
- 三个返回码为 0、stderr 为空、8/8 committed、owned residual=0。

任一项失败即 `do_not_pass`，同一 runtime 不自动重试。
