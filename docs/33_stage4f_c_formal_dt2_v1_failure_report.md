# Stage 33 C dt/2 probe failure

终态：`STAGE4F_C_FORMAL_DT2_V1_GATE: do_not_pass`。

Stage 33 合同和离线测试通过（2/2，compileall 通过），但唯一授权的 C attempt 在 factory 初始化阶段因目标 case 目录预先存在而触发 `FileExistsError`。失败发生在 step 0、任何 checkpoint/force snapshot/solver 进程启动之前：physical committed=0，fully audited=0，MATLAB/OpenFOAM 未启动。按停止条件未在同一 runtime 重试，未启动其他 CFD 分支。

Stage 23--32 旧证据、A/B 结果和父 checkpoint 未修改。该失败属于 case 初始化环境根因，不是 CFD、稳定化、mapping、ANCF/EB、数值门槛或比较合同根因。C 需要新的独立授权和全新 attempt 才能继续；不得据此宣称正式 C 或完整 A/B/C 通过。
