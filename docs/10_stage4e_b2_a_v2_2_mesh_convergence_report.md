# Stage 4E-B2-A-v2.2：最大Re laminar网格收敛

- 三套网格 checkMesh：`True`。
- coarse：cells `2880`，production max CFL `0.3403134247259821`，St `0.1496179580157639`。
- medium：cells `5120`，production max CFL `0.4615920850895595`，St `0.14970352733690534`。
- fine：cells `11520`，production max CFL `0.8033178440750729`，状态 `not_evaluable_frequency_consistency_or_cycles`。
- 网格收敛子门：`False`。fine 在 `CFL >= 0.8` 在线停止，故不满足正式生产有效性，不能计算通过的 medium→fine 收敛。

不得降低 CFL 或统计阈值。
