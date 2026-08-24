# 持久结构 runner 契约

阶段三使用一个长期存活的 MATLAB worker，Python 只负责顺序发送 JSON 请求。ANCF 与 EB 均实现 `initialize`、`predict`、`correct`、`get_motion`、`get_energy`、`save_checkpoint`、`load_checkpoint`、`finalize/shutdown`。

`predict` 在状态副本上推进，不覆盖已校正状态；`correct` 只对相同 step 使用新载荷推进一次。两分支输入均为 `nSlice × 3` 的守恒积分力，输出运动字段和能量字段同名。请求/响应由临时文件加原子替换提交，MATLAB 进程全程保持运行。

证据：`tests/structure_runners/test_structure_runner_contract.m` 通过 EB/ANCF 20 步、预测不污染状态和 checkpoint reload；Python 持久 worker 也完成重复输入一致性检查。实现位于 `src/coupling/structure_runners/`。

限制：当前 ANCF runner 的预张力参考能量含有常数基准项，能量审计采用增量和能量不平衡，不直接比较绝对参考能。
