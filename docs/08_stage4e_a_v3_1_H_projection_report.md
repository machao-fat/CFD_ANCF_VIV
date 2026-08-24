# Stage 4E-A-v3.1 正式 ANCF H 投影报告

## 审计范围

v3.1 只调用只读生产映射：

`src/coupling/multi_slice_mapping/mapping.py::build_H_for_manifest -> ancf_hermite_H`

对 nElem=8、16，分别对零交叉约束候选中心和均匀 7 切片中心生成 H 维度/非零项审计。生产映射文件 SHA-256 为 `178563a5d11e1033ec147518373d8fe4332187e4f4c7d251ff45422afe1b666d`。H 行为 3×54（nElem=8）和 3×102（nElem=16），节点排列遵循正式 `[r_x,r_y,r_z,r_sx,r_sy,r_sz]` 定义。

## 阻断原因

正式 H 位移投影需要同一目标模态的真实 ANCF 节点位置和斜率自由度。只读的 `results/08_stage4e_physical_baseline/ancf_design_raw.json` 只保存：

- `modal_shape_samples`；
- `modal_shape_samples_s_m`；
- `dry_mode_direction_xy`；
- 频率、节点数、自由度数和静力摘要。

它不保存 `modal_node_positions`、`modal_node_slopes`、`modal_q_vectors` 或 eigenvectors。因而本任务没有真实 ANCF 模态 q 可供 Hq 计算。

按照任务规定，不能把 201 点归一化形状差、正弦解析形状或合成零状态冒充正式 H 投影。v3.1 只保留了生产 H 函数的契约调用和维度证据，正式 8 vs 16 模态 H 投影状态为 `blocked_formal_modal_state_unavailable`。

## 决定

频率差、子空间 MAC 和物理 H 位移综合相对差没有在本报告中被重新包装成正式通过证据；nElem=8 最低生产网格、nElem=16 推荐参考网格均不冻结。需要后续从真实 ANCF 求解/模态流程导出节点位置、斜率和方向匹配后的 q，再单独完成 Hq 审计。
