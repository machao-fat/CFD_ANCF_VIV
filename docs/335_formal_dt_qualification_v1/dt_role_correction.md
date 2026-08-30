# Stage335 时间步角色更正

Stage335 使用的 `dt=0.00125 s` 是项目冻结配置中的 fine sensitivity level，不是当前生产默认时间步。当前 CFD 配置冻结为：

- production coarse: `dt=0.0025 s`;
- fine sensitivity: `dt=0.00125 s`。

因此 Stage335 的 `sigFpe` 只说明该 fine-dt 隔离试验未通过，不能替代或否定 production-coarse `dt=0.0025 s` 的资格测试。原有 case、物理参数、ANCF/EB 核心和历史 runtime 均未修改。下一次正确的 1 s qualification 应使用 `400` 步、`dt=0.0025 s`，并使用全新的 stage/run/case/runtime。
