# Stage 4F-C dt/2 冲量 forensic

Gate：`STAGE4F_C_DT2_IMPULSE_FORENSIC_V1_GATE: pass`。根因分类：`raw_cfd_transient_time_step_sensitivity`。

独立读取 Stage20 A 与 Stage21 C 执行 JSON 中的 raw/applied 三 slice 力，按各自 dt 做梯形积分。A raw xy 冲量为 `[1425.7322642085305, 5.544546819461197]`，C 为 `[1387.0286893071122, 4.972133465255179]`，相对差 `[0.02714645370174313, 0.1032389792790394]`。A applied 为 `[975.6925351189508, 5.879864256121626]`，C 为 `[1147.8264664195258, 5.1446585944895835]`，相对差 `[0.17642231041522669, 0.12503786305382938]`。

两分支物理起止时间一致，C tick 加密但端点相同；checkpoint 行包含当前 step、time_tick、raw/applied force、stabilizer state 和 committed transaction。未发现 force freshness、重复消费、缺样本、span/Aref、符号或单位转换错误。首次超过 5% 的共同时间点约为 `1.510 s`：A step 0 对 C step 1，slice 1，横向 y 分量，相对差约 `111.16%`，随后差异持续。这支持早期 raw CFD 横向初始瞬态对 dt 的敏感性，并且 applied 差异同步放大；不能归因于末端端点或积分规则。

该诊断不接受 Stage21 C，也不修改阈值、稳定化算法或旧证据。最小后续动作是申请独立、明确范围的初始瞬态时间层诊断；不得直接进入更大切片或长时 VIV。
