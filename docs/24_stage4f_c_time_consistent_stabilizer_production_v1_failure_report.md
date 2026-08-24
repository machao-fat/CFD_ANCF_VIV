# Stage 24 时间一致稳定化生产验收冻结失败报告

`STAGE4F_C_TIME_CONSISTENT_STABILIZER_PRODUCTION_V1_GATE: do_not_pass`

唯一终态：`frozen_contract_failure`。

首次失败发生在 Phase 1 合同冻结。Stage 23 已授权的完整精度 `tau_s` 是 `0.023728053952574758`，Stage 24 运行前合同草稿误写为 `0.023728514501552096`。相对误差约 `1.9409471e-5`；在 `dt=0.0025 s` 时，草稿给出 `alpha=0.09999815954114555`，不等于授权值 `0.1`。

合同草稿之后已创建生产 hook 草稿，因此不能通过静默改写 JSON 把合同重新描述为“修改前已冻结”。按失败停止条件，未执行 P/Q、A/B/C、MATLAB、OpenFOAM 或 WSL。仅运行了 4 项最初的离线 hook 草稿测试；完整 compileall、专项、相关回归和根目录 unittest 未进入正式验收序列，不能报告为 Stage 24 通过。

对共享 `atomic_checkpoint.py` 和 `scheduler.py` 的未验收编辑已撤销；Stage 24 合同、hook 和测试草稿保留作为失败证据。父 checkpoint 实测 hash 仍为 `5db86ae104015d51a8268862a1551579d96d0d80d82ddc7f55536371efc0334e`，Stage 20-23 旧证据未修改。

最小修复建议：新建独立 attempt/stage，直接从 Stage 23 immutable candidate contract 解析 tau 并先冻结其来源 hash；在任何生产文件编辑前验证 `alpha(0.0025)=0.1` 和两半步记忆衰减等价。另需把真实 raw snapshot path/hash/size/mtime 从 process 显式传入 checkpoint，不能用数值矩阵 hash 冒充 artifact identity。
