# Accepted Source Dual Run Repair 004

此前 dual-run 记录使用了 `confirm_025` 的 step603/time2.2575，不能证明 accepted source 的一致性。本次建立了全新 `matlab_dual_010`：

- accepted source：global step 559；time 2.2075 s；tick 2207500000；
- MATLAB R2021b return code：0；
- C++ worker startup：1；
- 40/40 engineering-tolerance pass；
- strict diagnostic：0/40；
- owned residual：0。

此次只读旧 MAT 模型结构，并在新 runtime 中写入 accepted checkpoint 的状态和 force；旧 MAT、accepted checkpoint、Stage 1--96 证据均未修改。

这证明了 accepted source 上的 transport/工程容差双算，但不证明 bitwise 或严格数值等价；`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`。OpenFOAM/WSL/CFD 未启动，真实 bounded confirm 仍等待明确授权。
