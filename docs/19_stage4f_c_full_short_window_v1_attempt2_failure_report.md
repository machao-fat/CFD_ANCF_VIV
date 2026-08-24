# Stage 4F-C attempt2 失败报告

唯一 Gate：`STAGE4F_C_FULL_SHORT_WINDOW_ATTEMPT2_GATE: do_not_pass`。

自动 MATLAB 探针一次通过：R2021b、win64、`license('test','MATLAB')=1`、return code=0，TEMP/TMP/TMPDIR/PREFDIR/PYTHONPYCACHEPREFIX 均位于 D 盘。stdout 原样保留了 MATLAB 退出期 Java preference/service warning；未据此认定许可证失效。旧 B timeout 的进程审计显示 correct worker return code=1、空日志、超时后无 correction/checkpoint，属于旧 worker/wrapper 事件。

attempt2 A 从同一父 checkpoint 全新运行 20/20 步，时间 1.5075 -> 1.5575 s，通过数值门槛。B 前 5 步通过并关闭；restart 段完成 global step 5--10 共 6 步后，在首个失败 global step 11 的 checkpoint freshness 审计处停止：`consumed force file changed after checkpoint`。CFD solver return code、CFL、raw Cd、速度、虚功、力转换和几何在已完成行均通过，但 transaction/checkpoint 身份失败，因此不得继续 B，不得启动 C。

attempt2 目录、partial fields、日志、checkpoint 和 MATLAB stdout/stderr 均保留。旧 Stage 19 和父证据未改写。根目录 unittest 实际 `842` 项，`841 OK`、`0 failure`、`1 error`；唯一 error 是旧 Stage 19 B `matlab_environment/tmpdir` 历史目录扫描异常，原始日志保留。

下一授权点仅为修复 restart 后 consumed force 文件的不可变副本/路径隔离并重新执行 A/B；本 Gate 不构成 C 授权。
