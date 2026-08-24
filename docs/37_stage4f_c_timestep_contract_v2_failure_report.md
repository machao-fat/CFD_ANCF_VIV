# Stage 37 revised timestep contract failure

合同修订离线阶段通过：dt=0.0025 被标记为 `rejected_coarse_timestep`，dt=0.00125 为候选 baseline，dt=0.000625 为 verification；5% 门槛和物理合同未改变。Stage 37 专项 2/2，根目录 `904/904 OK`（1 项既有 symlink skip）。

全新 10+30 restart attempt 完成 40/40 physical committed 和 40/40 fully audited。checkpoint=40、raw snapshots=120、lineage 连续、UTF-8/mtime_ns/tick/identity 通过，owned process=200/200/0（MATLAB 80、WSL/OpenFOAM 120）。硬数值门槛全部通过：max CFL `0.06819895002072694`，max raw |Cd| `4.251335917407953`，velocity `0.00015075510372612594`，virtual-work `4.1254892865546884e-16`，force conversion 0，geometry `5.551115123125783e-17 m`。

但新 restart 分支与 Stage 34 连续 C 的逐共同 tick 比较失败，最大 raw force xy 相对差 `0.6421269377152358`，远大于 q/qdot/qddot/force/stabilizer restart 合同的 `1e-11` 要求。该失败发生在 restart identity/state continuity 层，不是 MATLAB、OpenFOAM、CFL、Cd、mapping 或数值硬门槛失败。未在同一 runtime 重试，未启动其他 CFD。

Gate 冻结为 `STAGE4F_C_TIMESTEP_CONTRACT_V2_GATE: do_not_pass`。dt=0.00125 baseline 尚不能接受；dt=0.000625 仍仅为诊断验证。下一授权点是对 restart state 与连续 C 不一致的独立 forensic，不能放宽比较阈值或直接宣称 baseline 接受。
