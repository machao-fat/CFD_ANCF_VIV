# Stage 4E-A-v3.2.2：最终九切片协议身份物化与跨工件一致性报告

状态：`completed`。本阶段只做离线身份物化和一致性收口；未运行 MATLAB、Monte Carlo、H 重算、OpenFOAM 或真实 CFD。

## 选定候选

唯一最终候选为 `zero_crossing_aware_9_point_sampling`。完整精度边界、中心、长度和速度读取自 v3.2.1 独立结果，不重新优化、不重新采样：

`[0, 0.1292558279354895, 0.280797829045388, 0.4145061199726363, 0.474290780141844, 0.5249612781341336, 0.6197764498785212, 0.7577318115362272, 0.8521486350114472, 1]`

## 正式协议身份

新建正式 0.2.1 `SliceManifest`，切片数为 9；新建绑定该 manifest 的 `RuntimeConfig`。最终 case ID 为：

`stage4e_v3_2_2_final_zero_aware_9`

物化后的 hash：

- `slice_manifest_sha256 = 995e2cd958dda81ea00574187a7b189785f28d54266839debd11976bcd3a7860`
- `config_sha256 = fd847246d3e0ed00ec49d3a53644bd32651d6e185ac0cb7c33f91a8da056e677`

manifest 和 RuntimeConfig 均由生产 0.2.1 数据类解析，hash 可重复计算；路线 G 字段未注入正式对象。

## H 结果绑定

本阶段只读取 v3.2.1 已完成的九切片 H 结果，未重新计算 H。H 结果确认：

- nElem=8：`9×3×54`
- nElem=16：`9×3×102`
- `all_targets_pass = true`
- target mesh recommendation：`nElem=8`
- 诊断标签：`shape-scaled modal projection diagnostic`

H 结果通过 `final_manifest_sha256` 与新的九切片 manifest 绑定；不得把该诊断解释为真实 VIV 幅值误差。

## 跨工件一致性

manifest、RuntimeConfig、H、Route-G flow profile、checkpoint binding 全部具有：

- 同一 selected candidate：`zero_crossing_aware_9_point_sampling`
- 同一 case ID：`stage4e_v3_2_2_final_zero_aware_9`
- 同一切片数：9
- 同一几何 hash
- 同一 manifest hash
- checkpoint 与 flow profile 的 hash 绑定一致

跨工件身份结论：`passed`。任何 7 切片工件替换到最终身份位置都会被验证器拒绝。

## 路线 G

独立 flow profile hash：`28238a9623a07dd5e8f6e940678377f0a9975035236749c0dbf7a916e1dfd90e`。

名称严格为 `flow_profile_sha256`，不是正式 `config_sha256`。路线 G 状态仍为 `provisional_pending_reverse_flow_smoke`；路线 L 仍未升级为正式协议。
