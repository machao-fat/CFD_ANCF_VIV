# Stage 4E-B2-A 固定圆柱目标Re模型、网格与时间步 pilot

## 结论

本报告只覆盖二维、单位跨距、静止圆柱的目标Re数值pilot，不覆盖九切片CFD、CFD–ANCF耦合、自由VIV、锁定区或试验验证。上游 Stage 4E-A 九切片身份保持为 `28238a9623a07dd5e8f6e940678377f0a9975035236749c0dbf7a916e1dfd90e` 对应的父路线G flow profile；B1 仅作为路线G边界烟测来源，Re=100烟测不能替代本pilot。

本次 run_id 为 `20260814T051204411Z_stage4e_b2_a_retry3`。两组10步预检通过；正式suite完成 4 个案例后因 `runtime:high_kOmegaSST_fine` 停止。高Re SST fine 的最大CFL为 0.9920，触发“CFL达到或超过0.8必须停止”，故没有继续dt/2、域敏感性和低/中Re确认。

## 目标Re和模型候选

低/中/高候选直接取父九切片非零速度幅值的最小值、中位排序值和最大值：切片4/6/0，对应Re约1427.53/4352.81/12334.02。pilot使用正等效速度幅值，保留源切片有符号速度和方向元数据；这不是把正向pilot冒充真实负向路线G工况。

模型候选仅为二维 laminar 与二维 URANS k-omega SST。Norberg及Williamson文献用于解释Re依赖和三维尾流限制，不用于替换本pilot数据。实际模型比较结果、力系数、PSD和时间窗见 `results/10_stage4e_target_re_pilot/` 下JSON。

## 网格、时间步和停止条件

网格族保持圆柱、域边界和block拓扑一致，coarse/medium/fine每个二维block的径向/切向单元分别为8/16/24；实际完成的checkMesh均为 Mesh OK。SST fine的最大CFL超过0.8，因此网格收敛、dt收敛和域敏感性不能冻结；SST y+在本次默认日志/post-processing中未报告，不能声称满足y+<=1。

正式统计丢弃前30%瞬态并划分3个窗口；已完成案例的统计窗有效周期不足要求的10个有效脱涡周期或窗口指标不稳定，不能冻结统计模型。频率只作为诊断，不作VIV或锁定区结论。

## Gate判断

离线B2-A Gate：**建议不通过**。停止条件为 CFL>=0.8；模型筛选、网格收敛、时间步收敛、域敏感性和低/中/高Re确认均未同时完成。所有失败案例、日志和D盘进程清理证据均保留。

详细官方软件来源和同行评议文献见 `literature_comparison.json`。OpenFOAM v10的pimpleFoam/forceCoeffs设置仅用于候选固定圆柱pilot。

## 机器可复核入口

- 父身份：manifest `995e2cd958dda81ea00574187a7b189785f28d54266839debd11976bcd3a7860`，config `fd847246d3e0ed00ec49d3a53644bd32651d6e185ac0cb7c33f91a8da056e677`，flow profile `28238a9623a07dd5e8f6e940678377f0a9975035236749c0dbf7a916e1dfd90e`。
- 预检：`precheck_summary.json`。
- mesh：`mesh_family.json`、`mesh_convergence.json`。
- 力和统计：`force_coefficient_summary.json`、`statistical_stationarity.json`。
- 进程：运行时目录中的 `owned_process_registry.json`、`owned_process_cleanup_audit.json`。
