# Stage195 C++ worker persistent IPC 有界 Confirm 报告

## 结论

`STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: pass`

本次仅执行一个全新的 40-step、3-slice、0.05 s 有界 confirm。源为 global step 559、2.2075 s、tick 2207500000；最终到达 step 599、2.2575 s、tick 2257500000。40/40 physical committed，40/40 fully audited，未启动下一个 segment。

本结果验证了已通过数值等价审查的 C++ ANCF worker 与持久 IPC 在真实三 slice CFD 路径上的一次有界运行。它不构成 Strouhal、稳定 VIV 响应或 lock-in 的正式结论。

## 计时

| 指标 | 结果 |
| --- | ---: |
| Segment wall-clock | 22.1760407 s |
| 每步 wall-clock mean / P50 / P95 / max | 0.522335405 / 0.423686800 / 0.468102205 / 4.479966300 s |
| `T_ancf` mean / P50 / P95 | 0.020413390 / 0.020381750 / 0.020723270 s |
| `T_openfoam` barrier mean / P50 / P95 | 0.302358388 / 0.312683600 / 0.316343730 s |
| `T_exchange` mean / P50 / P95 | 0.193415642 / 0.084896850 / 0.122675535 s |
| `T_sync_and_audit` mean / P50 / P95 | 0.019240703 / 0.019070350 / 0.020539130 s |
| 相对 35.4478716 s 基线加速比 | 1.598476125x |
| 相对 37.1570657 s 基线加速比 | 1.675550032x |

`T_openfoam` 为三个并行 slice 的 barrier 墙钟，而非三者求和。slice 0/1/2 的均值分别为 0.485461962 / 0.489569973 / 0.488984403 s；slice 1 略慢。首步产生约 4.2 s exchange/初始化异常值，致使均值与 P50 差异显著。计时存在重叠：各阶段不能相加；`T_unattributed_coordinator` 只是重叠/协调诊断项，不得解释为额外可加成本。

## 正确性与清理

Stage186 已完成 MATLAB/C++ 严格数值等价验证，`C++_ANCF_NUMERICAL_CORE_STATUS=validated`。本 confirm 未启动 MATLAB，也没有以 transport 成功替代数值验证。

| 进程 | 实际启动数 |
| --- | ---: |
| C++ worker | 1 |
| MATLAB | 0 |
| OpenFOAM | 3 |
| WSL | 3 |
| CFD | 3 |
| owned residual | 0 |

C++ worker 与全部三个持久 OpenFOAM slice 返回码均为 0、清理状态均为 `closed`，各 slice 日志均含 `End`。40 个 checkpoint 和 committed journal 均存在并连续；旧证据和旧 runtime 未修改，旧 runtime 未复用。

## 边界

本次不修改 ANCF/EB 物理语义、物理参数、global dt、slice 数、稳定化参数、数值阈值、统计门槛或正式 0.2.1 协议。没有启动 Stage75、E5-B、E5-C、五/九 slice、长时 VIV、锁定区或实验验证。

`FORMAL_STROUHAL_STATUS=not_completed`

`STABLE_VIV_RESPONSE_CLAIM=not_completed`

`LOCK_IN_CLAIM=not_completed`

任何新的 CFD segment 仍需新的明确授权。
