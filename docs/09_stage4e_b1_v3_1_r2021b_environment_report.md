# Stage 4E-B1-v3.1-R2021b 新 MATLAB 环境与证据链报告

状态：`partially_completed`。本报告只覆盖 R2021b 安装审计、唯一一次版本/许可证探针、D 盘运行时卫生和进程证据链。

- 选定启动器：`D:\Program Files\MATLAB\R2021b\bin\matlab.exe`
- 启动器 SHA-256：`49fd776ad00fde92a428b99fb12f43a5d99194dd3fc3b2000886f2fc64ab360b`
- 核心 MATLAB SHA-256：`6dd103950dde9d1ff9826c220a43259719445d67516d619f3ba8d3221094e0ce`
- 旧路径存在：`False`
- 探针 run_id：`20260813T161401Z_55ba4443dd`
- 探针状态：`environment_blocked`；阻断原因：`matlab_version_license_probe_checks_failed`
- release 检查：`True`；9.11 系列：`False`；win64：`False`；许可证：`False`
- 事件日志 SHA-256：`e666213cfe3c2984bae83c818fdff79f4578f5c44904a1f00358e632a90c04b2`；事件链审计来源：D 盘原始 JSONL
- 进程清理：started=`3`，closed=`3`，residual=`0`

探针失败后未启动 worker、smoke、正式 ANCF 测试，也未执行未过滤的根目录回归。MATLAB 原始输出保留在 D 盘 runtime 日志中，结构化结果仅引用其摘要和哈希。
