# Stage 4E-B1-v2 运行时卫生与项目回归收口

状态：`partially_completed`。

本阶段完成了 `PersistentANCFRunner` 的启动失败清理、owned process-tree 登记、创建时间校验、幂等 shutdown、D 盘任务运行时目录和 unittest `addCleanup` 修正。fake worker 生命周期专项 `11/11` 通过，B1 CFD 专项保持既有 `24/24` 证据且未重跑 OpenFOAM；正确的非 MATLAB 回归实际收集并通过 `359/359`。

任务 owned 进程聚合登记 `126` 个，关闭 `126` 个，残留 `0`；后审计确认项目 runtime 活动进程 `0`，unrelated/historical MATLAB 未被终止。C 盘项目工件创建数为 `0`，运行时路径审计通过。

MATLAB 版本探针在 45 s 内无输出。随后一次错误的全量收集把 4 个真实 persistent ANCF 用例纳入，4/4 均在 initialize 阶段环境阻断；其 launcher/child 均已按 PID、创建身份和父子关系清理。该收集错误和停止条件已留存在 D 盘日志，真实 persistent ANCF 子门仍为 `environment_blocked`，完整根目录回归不宣布通过。项目级 Gate 建议不通过。

任务运行目录：`D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\stage4e_b1_v2\20260813T160000Z_closeout`。C 盘基线、后审计、差异文件、进程登记和关闭审计均位于该目录；不删除任何基线或失败证据。

路线 G CFD 子门仍可接受为 B1 原证据范围内的 `建议通过`，但本阶段不扩大到真实高 Re、九切片或 VIV。
