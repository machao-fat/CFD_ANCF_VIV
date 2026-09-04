# Stage 285 单切片 ANCF-preCICE 离线适配报告

## Gate

`STAGE4F_D_PRECICE_ANCF_ADAPTER_OFFLINE_V1_GATE`

本阶段仅建立隔离的 ANCF/C++ worker 与 preCICE 数据边界，未启动 MATLAB、OpenFOAM、WSL 或 CFD。固定合同为 OpenFOAM 10、preCICE 3.x、`dt=0.005 s`；没有复用 Stage 1–284 runtime 或证据。

## 验证内容

- `global_step`、`case_local_bridge_step`、`time_s`、`integer_tick` 由 `BridgeClock` 统一生成；示例 global 559 -> local 7、global 560 -> local 8，local 编号不直接等于 global 编号。
- 位移按 `H` 做 consistent 映射，力按 `H^T` 做 conservative 映射，并验证虚功一致。
- 每个 envelope 含完整 run/case/slice、request/transaction、sequence、payload hash、ack 字段；canonical UTF-8 JSON、NaN/Inf、tick、hash 和身份错误均 fail-closed。
- 三切片 barrier 必须等待 `slice_0000/0001/0002` 三个 consumed ack 后才 commit；stale、duplicate、乱序、错误 slice、timeout 和 disconnect 均 fail-closed。
- `q/qdot/qddot` restart state、原子 latest checkpoint/restart/force 及完整 step journal 均通过离线测试。

## 结果

专项测试 13/13 通过，compileall 通过；MATLAB/OpenFOAM/WSL/CFD 启动数均为 0，owned residual=0。只修改 Stage 285 新增目录，未修改 ANCF/EB 核心、物理参数、global dt、数值阈值、正式协议或历史证据。

Stage 285 通过后，才允许使用全新 runtime 执行 Stage 286 单切片 `0.20 s/40 steps`；本报告不授权三切片真实 smoke。
