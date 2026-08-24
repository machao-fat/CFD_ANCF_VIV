# Stage 4E-A-v3.2.2 Sol 主 Agent 验收

## 结论

Stage 4E-A 离线 Gate：`passed_with_scope_limits`

Stage 4E-A-v3.2.2 已将最终推荐的 `zero_crossing_aware_9_point_sampling` 统一物化为正式 0.2.1 manifest/config、路线 G flow profile、checkpoint binding 和 H/网格身份。此前 7/9 切片错配已解决。

本次通过只代表离线物理输入、结构离散和协议身份闭环，不代表真实九切片 CFD–ANCF、长时间 VIV、锁定区或严格试验幅值验证完成。

## 独立复核

- 正式 case_id：`stage4e_v3_2_2_final_zero_aware_9`
- 切片数：9
- slice_id：0–8
- manifest SHA-256：`995e2cd958dda81ea00574187a7b189785f28d54266839debd11976bcd3a7860`
- config SHA-256：`fd847246d3e0ed00ec49d3a53644bd32651d6e185ac0cb7c33f91a8da056e677`
- flow profile SHA-256：`28238a9623a07dd5e8f6e940678377f0a9975035236749c0dbf7a916e1dfd90e`
- checkpoint binding SHA-256：`019bbf4b804a98c1abd34c73a19287587e444d060cb244b8a9973250e486d572`
- manifest、RuntimeConfig、H、flow profile 和 checkpoint binding 的跨工件身份审计：通过。
- H 候选：九切片；nElem=8 H 为 9×3×54，nElem=16 H 为 9×3×102。
- CF1、IL2、IL4 的频率、MAC 和切片中心投影阈值：全部通过。
- 目标结构网格：nElem=8；nElem=16 保留为参考网格。
- 路线 G 状态：`provisional_pending_reverse_flow_smoke`。
- MATLAB、Monte Carlo、H 和 OpenFOAM 均未在本阶段重新运行。

## 独立测试

- `python -m compileall -q src tests`：通过。
- v3.2.2 专项测试：9/9 通过。
- 根目录全项目测试：320/320 通过，耗时约 101.779 s。

## Gate 决定

- 离线 Stage 4E-A：通过，但保留范围限制。
- 九切片方案：冻结为离线候选。
- nElem=8：冻结为最低生产候选网格。
- 路线 G：仅允许进入独立的正向/反向刚性圆柱边界烟测。
- 九切片真实 CFD–ANCF：暂不授权。
- 自由 VIV、长期统计、锁定区和严格幅值验证：暂不授权。

## 下一准入条件

下一阶段必须先证明在同一圆柱网格和相同绝对 Reynolds 数下：

1. 正向来流和反向来流均稳定完成；
2. 上游/下游边界角色按流向正确交换；
3. 反向速度没有通过错误反射或额外旋转载荷实现；
4. 镜像后的全局阻力符号翻转、升力统计量按对称关系一致；
5. 最大 CFL、质量守恒、力系数、频率和场镜像误差满足冻结阈值；
6. 结果具有新鲜案例、来源 hash 和失败保留证据。

该烟测通过后，Sol 主 Agent 才能决定是否进入九切片静态/规定运动 CFD 原型。
