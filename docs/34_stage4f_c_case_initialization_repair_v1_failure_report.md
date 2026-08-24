# Stage 34 case initialization repair and formal C result

终态：`STAGE4F_C_CASE_INITIALIZATION_REPAIR_V1_GATE: do_not_pass`。

目录所有权首次分叉位于 Stage 33 外层编排：外层预创建了 factory-owned branch `C`，而 `DiagnosticEngine` 要求目标不存在。Stage 34 runner 只创建 Stage 34 父容器，由 factory 独占创建 `C`。专项测试 4 项执行，3 项通过；Windows 当前权限不允许创建 symlink，相关测试明确跳过。初始化修复已接受，Stage 33 失败目录未复用。

全新 C 使用 run_id `stage34_formal_C_case_owner_v1`，完成 40/40 physical committed 和 40/40 fully audited，时间 tick `1508750000` 至 `1557500000`。40 个 checkpoint lineage 连续；120 个 raw snapshots 的 path/hash/size/mtime_ns/identity 全部通过。owned process 200/200/0（MATLAB 80、WSL/OpenFOAM 120），return code 全为 0。

C 最大值：CFL `0.06819895002072694`，raw/applied |Cd| `4.251335917407953 / 1.0931100950061452`，velocity consistency `0.00015075510372612594`，virtual-work relative error `4.511936022116914e-16`，force conversion `0`，geometry error `6.938893903907228e-17 m`。

冻结 A/C 比较未通过。raw x/y impulse normalized difference 为 `0.057765616492638706 / 0.002306025190631599`；applied x/y 为 `0.009116491932023563 / 0.0014486219745579636`。raw x 超过 0.05 门槛，因此不能接受 C 或完整 A/B/C。endpoint position/D `1.747651352375516e-06`、velocity/U `0.0004539892660464192`；min/max tension relative difference `1.1975748909464508e-05 / 2.486927091096758e-06`，均通过。该结果保留早期瞬态时间步敏感性风险，不构成完整 CFD 时间收敛证明。

compileall 通过；Stage 34 专项通过（1 项环境权限跳过）；根目录 `898/898 OK`（1 项跳过）。父 checkpoint 实测 SHA-256 为 `5db86ae104015d51a8268862a1551579d96d0d80d82ddc7f55536371efc0334e`。用户提供的转录值不足 64 位，已作为 hash 转录冲突记录，父文件未修改。

下一授权点需要针对正式 A/C raw x impulse 超阈值的独立取证或研究合同决策。五/九切片、长时 VIV、锁定区和实验验证均未启动。
