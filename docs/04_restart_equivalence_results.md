# Restart 分层结果（已更新）

- 严格逐步/bitwise 等价：未通过，`restart_checked_strict=false`；
- native/file 适配器重启一致性：通过，横向力相对 RMSE `1.0787e-11`；
- 工程 restart 一致性：通过。最大力差 `0.32040383 N`，相对于 500 N 为 0.06408%，且重启后首两个样本之外降至 `0.00024638 N`。

该短暂边界差异不得写成 `ancfFileMotion` 失败，也不得写成严格逐步等价通过。量化结果见 `results/04_restart_equivalence/restart_engineering_acceptance.json` 和原始 `restart_equivalence.json`。
