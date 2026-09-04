# Stage 268 公开 CFD 基准报告

## 结论

Stage 268 的有界 Gate 通过：公开仓库 `hojjatnaderi/Validated-VIV` 已在现有 OpenFOAM 10 / WSL Ubuntu-22.04 环境中完成兼容改造，并完成 1 s 动态 smoke（200/200 步）。本阶段只证明算例可运行和动态网格配置有效，不宣称文献级 VIV 统计验证完成。

## 来源与许可证

- 来源：<https://github.com/hojjatnaderi/Validated-VIV>
- commit：`adc4a809cdcb2cf9a190c96040889fd39e1d4493`
- 许可证：BSD-3-Clause
- 原始参考副本：`references/public_viv_benchmarks/Validated-VIV`
- 原始副本保持只读参考；运行副本位于 `cases/openfoam/stage268_validated_viv_of10`

## OF10 兼容改造

只改动隔离副本：

1. 将旧版顶层动态网格配置改为 OF10 的 `mover/type motionSolver` 和 `rigidBodyMotionCoeffs` 结构。
2. 加载 `libfvMeshMovers.so` 和 `librigidBodyMeshMotion.so`。
3. 将 `outputControl/outputInterval` 改为 OF10 推荐的 `writeControl/writeInterval`。
4. 增加只允许 OpenFOAM 10 的 `Allrun` 入口。

质量、惯量、自由度、弹簧、阻尼、网格、`deltaT=0.005`、Re=100 工况参数未改动。

## 运行证据

- 网格：50,232 cells；拓扑检查通过，原始网格有 604 个 concave cells 警告。
- `potentialFoam`：成功，连续性误差约 `1.18e-6`。
- 1 s `pimpleFoam`：200 步，最终时间 `1.0 s`，return code=0，日志包含 `End`。
- 动态网格：日志显示 `rigidBodyMotion` 和 `Newmark`，圆柱中心发生连续位移。
- 累计连续性误差约 `8.0e-13`。
- 1 s 墙钟时间约 276 s（单进程，约 50k cells）。

原始日志：

- `results/268_public_cfd_benchmark_v1/checkMesh_raw.log`
- `results/268_public_cfd_benchmark_v1/potentialFoam_attempt1_raw.log`
- `results/268_public_cfd_benchmark_v1/pimpleFoam_smoke_attempt3_raw.log`
- `results/268_public_cfd_benchmark_v1/pimpleFoam_1s_attempt1_raw.log`

机器可读 Gate：`results/268_public_cfd_benchmark_v1/stage4f_d_public_cfd_benchmark_v1_gate.json`

## 进程与保护

本次按用户授权运行了公开 CFD 基准：MATLAB=0，OpenFOAM=1，WSL=1，CFD=1；owned residual=0。Stage 1–267 旧证据、失败 runtime、ANCF/EB 核心、正式 0.2.1 协议和正式统计状态均未修改。当前仍保持：`FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。

## 下一步

下一步不是立即接入三切片，而是锁定该 OF10 副本并完成公开基准的物理后处理：从 `forces1` 提取升阻力和刚体轨迹，检查主频/Strouhal 与仓库声明及文献的关系。通过后再复制同一 OpenFOAM case 做单切片 ANCF，最后比较文件交换和 preCICE 两个通信版本。preCICE 改造应保持为隔离适配层，不覆盖当前文件通信实现。
