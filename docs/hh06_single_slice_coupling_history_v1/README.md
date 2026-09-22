# HH06 单切片耦合全过程归档

本目录是 HH06 Case 1 高 Re 单切片 `Fluid_0000 -> preCICE -> Structure_0000 -> ANCF` 的问题、修复、资格测试和失败边界归档。

## 入口文件

- `HH06_SINGLE_SLICE_COUPLING_REPAIR_HISTORY_V1.md`：按时间顺序说明合同、问题、修复、验证和当前结论。
- `HH06_SINGLE_SLICE_COUPLING_REPAIR_HISTORY_V1.json`：机器可读的冻结合同、里程碑、执行边界和最终 gate。
- `evidence/`：本轮从本地 runtime 归档的 27 个报告、结果 JSON 和 lineage 测试脚本。

## 证据组织

`evidence/` 保留原 runtime 的相对目录结构，覆盖：

1. adapter Displacement read-path 修复及非零 ALE 一窗口资格；
2. 25-window force-unit-chain、ALE/流体/turbulence runaway 资格结果；
3. ALE displacement semantics / feedback audit；
4. Fluid rollback fingerprint audit；
5. preCICE Displacement read-path 和调用顺序设计审查；
6. real mesh rollback audit；
7. worker lineage transition 修复审计及原/修复测试结果。

更早阶段的 SHM1、worker build、offline runtime、initial-data、checkpoint lifecycle、transport-ID 和 Structure_0000 wrapper 文档已经在仓库既有路径保存，主报告中给出了对应阶段和结论。

## 当前结论

- `HH06_BOUNDED_MULTIWINDOW_ALE_QUALIFICATION = DO_NOT_PASS`；
- 主要 blocker：`LATE_WINDOW_ALE_FLOW_TURBULENCE_RUNAWAY`；
- 25-window 中 force scaling、checkpoint/rollback、transport ID 和字段恢复证据通过，但后期 `Co`、mesh Co、mesh velocity、`|U|` 和 `omega` 共同失控；
- lineage parity 修复仅在隔离 worker 测试中通过，未部署到 `slice0000`；
- 本归档不授权新的 50-window、0.2 s production FSI 或任何新 CFD。

## 归档边界

已上传：报告、JSON 结果、可复现的诊断测试脚本和修复说明。

未上传且未删除：OpenFOAM 时间目录、运行日志、socket/core dump、二进制、编译目录和缓存。这些大文件/运行态文件不适合作为公开 Git 历史的一部分。
