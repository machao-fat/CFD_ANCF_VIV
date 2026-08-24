# Stage 4D-C-A ANCF 结构离散收敛报告

## 执行边界

结构离散收敛规定为 `dt=0.00125 s` 下的 nElem=2/4/8、各 200 步，并以 nElem=4 与 nElem=8 为主要收敛对。本次时间步子 Gate 已在共同时间点比较中失败，故按协议没有启动任何 nElem=4 或 nElem=8 真实 CFD–ANCF 重型 campaign，也没有用部分结果替代结构收敛证据。

结构收敛结果文件明确标记为：

`results/07_stage4d_c_convergence/structure_mesh_convergence.json` → `status=not_run_blocked_by_time_step_gate`

`results/07_stage4d_c_convergence/selected_configuration.json` → `status=none`

## 离线映射与虚功检查

在不启动重型 CFD 的前提下，使用正式 H/Hᵀ 映射对 nElem=2、4、8 做了离线维度与虚功一致性检查。节点位置均按 `s_j=jL/nElem` 生成，切片中心保持 `[1.25,5.0,8.75] m`，切片长度只作为积分力输入一次。

| nElem | 节点 | 自由度 | 虚功相对误差 | 结果 |
|---:|---:|---:|---:|---|
| 2 | `[0,5,10]` | 18 | `0` | 通过 |
| 4 | `[0,2.5,5,7.5,10]` | 30 | `0` | 通过 |
| 8 | `[0,1.25,2.5,3.75,5,6.25,7.5,8.75,10]` | 54 | `2.220446049250313e-16` | 通过 |

这些是映射公式的离线证据，不是结构离散动态收敛证据。由于 nElem=4/8 没有真实运行，不能选择生产结构离散，也不能宣称结构网格收敛。

## 后续阻断项

时间步比较中的 `qdot` NRMSE 为 `0.3908521876924054`，`qddot` NRMSE 为 `1.0941190222479935`，超过 5% 门槛。因此严格 restart 和分级延时结果文件均写为 `not_run_blocked_by_time_step_gate`。本报告不作长期 VIV、锁定区或稳定振幅结论。
