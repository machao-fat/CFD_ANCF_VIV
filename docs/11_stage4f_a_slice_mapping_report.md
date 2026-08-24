# Stage 4F-A 3/5/9 切片映射状态

## 状态

**未冻结、未映射。**

结构候选门禁先于切片冻结触发硬停止条件。为避免产生可被误认为正式 `0.2.1` 协议 manifest 的文件，本轮结果目录中的三个 `*_slice_manifest.json` 都明确标记为 `not_a_protocol_manifest=true`；它们是停止状态记录，不得交给生产 driver 或 checkpoint 模块。

本轮没有调用：

- `build_H_for_manifest`；
- `ancf_hermite_H`；
- `H^T` 广义力映射。

因此 3/5/9 切片的插值、乱序、缺失/重复拒绝、`Δs` 一次权重、虚功 `≤1e-12`、广义力变化和 checkpoint 大小均不可评价。不得把 Stage 4C 的非均匀切片或高 Re 九切片身份冒充为本轮低 Re 均匀方案。
