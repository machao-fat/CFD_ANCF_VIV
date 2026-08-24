# Stage 4E-B1-v3.1.1 探针修正报告

状态：`environment_blocked`。

上一轮原始日志和事件链保留在 v3.1 目录，根因确认为 MATLAB `-logfile` 与 Python stdout 双写同一文件造成文本交错。本轮使用独立 `matlab_internal.log`、`launcher_console.log` 和 MATLAB 原生 UTF-8 `probe_payload.json`。

结构化字段中版本、架构、许可证和 D 盘路径检查通过；MATLAB 原生 `version('-release')` 返回 `2021b`，而冻结校验要求严格 `R2021b`，故按 fail-fast 判定探针失败。未补写 payload，未重跑探针。

事件日志 SHA-256：`cd484c7ba7efb1da2db8b971283d329fba38fd17b4d9de807636522683b9e3af`；owned residual：`0`；unrelated terminated：`0`。
