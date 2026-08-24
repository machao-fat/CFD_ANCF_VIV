# Stage 4F-C 数值稳定化设计评审

本轮仅完成离线伪 case 设计评审，未修改生产 scheduler、mapping、ANCF/EB 核心，也未启动真实 CFD。

对 D1 代表性交替力序列测试欠松弛 `alpha=0.1、0.25、0.5、1.0`。较小 alpha 降低响应幅值，但四组均保留 5 次符号翻转；因此欠松弛只能作为候选稳定化组件，不能单独宣称修复早期显式弱耦合失稳。

专项测试共 6 项，compileall 通过。任何 load relaxation、增量限制、step rejection 或 rollback 都会改变现行 0.2.1 交易语义，必须先冻结新协议、checkpoint lineage 和失败恢复合同，再进行实现或真实 CFD。

Gate：`offline_design_review_passed`；数值接受仍为 blocked。下一授权点是审查并批准一份新的耦合协议，而不是直接运行 A/B/C。
