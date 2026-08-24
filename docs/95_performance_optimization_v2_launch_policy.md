# Stage 95 Launch Policy

真实性能 benchmark 默认由 Codex 直接启动。只有失败证据明确出现 MATLAB、MathWorks 或 ApplicationService 上下文中的错误 `5001`，当前 runtime 才 fail-closed，并要求用户在自己的交互式 `SessionId=1` 中启动 runner。

普通 MATLAB 非零返回、timeout、`Java is shutting down`、EditorDataService/Connector warning、license 错误、OpenFOAM/WSL 错误或没有明确服务上下文的数字 `5001`，都不会触发 runner fallback；它们按原合同终止当前 runtime，不得同一 runtime 重试。

触发 fallback 后，旧 runtime 不得复用。用户必须启动全新 runner、全新 `run_id`、`case_id` 和 runtime；Codex 只读取并审计新的结果。该策略不修改 ANCF/EB 核心、物理参数、global dt、slice 数量、数值阈值、正式协议语义或旧证据。
