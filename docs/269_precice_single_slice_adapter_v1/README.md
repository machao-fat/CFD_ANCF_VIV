# Stage 269: isolated preCICE single-slice adapter

本阶段只完成通信合同、故障注入和 OpenFOAM 10 adapter 构建审计，不运行耦合算例。

## 结果

- preCICE：`libprecice.so.3`、`pyprecice 3.4.0`、OpenMPI 4.1.2 已由用户环境提供。
- 官方 `openfoam-adapter` OpenFOAM10 分支 commit `d53753b1c927b2413b02299c9da15725b3e772f0` 构建成功。
- 产物：`libpreciceAdapterFunctionObject.so`，大小 1,692,416 bytes；构建日志和动态依赖审计无 `not found`。
- 离线专项测试：8/8 通过。
- MATLAB、OpenFOAM solver、WSL CFD、CFD participant：本阶段新增启动数均为 0。

机器可读 Gate：`results/269_precice_single_slice_adapter_v1/stage4f_d_precice_single_slice_adapter_v1_gate.json`。

## 保护边界

preCICE 仅作为隔离适配层；旧文件通信、ANCF/EB 核心、物理参数、正式 0.2.1 协议语义和 Stage 1--268 证据未修改。此 Gate 通过不等于单切片耦合已验证，也不等于任何正式 VIV/Strouhal 结论完成。

下一授权点应是全新 runtime 的单切片固定/预设运动 preCICE smoke，仍不得直接进入三切片或长时 VIV。
