# Stage185 MATLAB 中间量 trace 修复报告

## 结论

MATLAB trace 尚未生成，阶段继续按 fail-closed 停止。唯一一次 MATLAB 启动执行了独立导出脚本；该脚本只扫描 `results/**/committed.mat`，因此返回：`expected exactly one matching source, found 0`。

随后只读解析确认受保护旧 runtime 中存在合法源：`runtime/cpp_worker_persistent_ipc_v1/matlab_dual_011/accepted_step559_seed.mat`。其 MAT 合同为 step=559、time=2.2075 s、tick=2207500000、dt=0.00125 s、Gauss=5、max_newton=50、q size=102；旧 process manifest 还记录该 seed 曾成功生成 MATLAB 黄金输出。Stage185 导出器已修正为显式验证该受保护 seed，但本阶段“MATLAB 最多启动 1 次”的额度已用完，所以没有第二次启动，也没有 C++ 中间量对照或代码修复。

## 进程与保护

- MATLAB 启动：1 次（batch 外壳产生的两个本次进程已清理）。
- OpenFOAM=0，WSL=0，CFD=0；owned residual=0。
- Stage1--184 旧证据、旧 runtime、MATLAB 参考实现、物理参数和阈值未修改。
- Stage184 的 `do_not_pass` 状态保持不变。
- Stage185 新工具目录的 Python `compileall`：通过。

## Gate

`STAGE4F_D_CPP_WORKER_MATLAB_INTERMEDIATE_TRACE_REPAIR_V1_GATE: do_not_pass`

`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`

需要新的明确 MATLAB 导出授权（允许在修正后的导出器上重新执行一次）后，才能进行同 schema 中间量导出。当前不具备 C++ 数值修复或 CFD confirm 申请资格。
