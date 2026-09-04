# Stage 293：C++ worker + preCICE 三切片 smoke

## 结论

`STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_040S_V1_GATE: pass`

本阶段完成一次全新的三切片短窗口验证：OpenFOAM 10、preCICE 3.4.1、`dt=0.005 s`、8 步、终点 `0.04 s`。三个 Fluid slice 均正常结束，单个 Linux C++ ANCF worker 在 WSL 中只启动一次并正常关闭。

## 证据

- Gate：`results/293_cpp_worker_precice_three_slice_040s_v1/stage4f_d_cpp_worker_precice_three_slice_040s_v1_gate.json`
- participant：`results/293_cpp_worker_precice_three_slice_040s_v1/structure_participant.json`
- barrier：`runtime/293_cpp_worker_precice_three_slice_040s_v1/logs/global_barrier.jsonl`
- wall-clock：`10.367960 s`
- 每个 slice：8/8；总记录：24；global barrier：8/8
- 三个 Fluid 返回码：0；C++ worker 返回码：0；owned residual：0
- MATLAB：0；OpenFOAM：3；WSL：1；CFD：3；C++ worker：1
- runtime 文件数：109；大小约 64,473,236 bytes

## 身份与映射

每个记录包含 `global_step`、`case_local_bridge_step`、`time_s`、`integer_tick`、slice identity、request/transaction identity、force hash 和 consumed ack。worker 使用 `q[1]、q[7]、q[13]` 投影到三个 slice 位移，并接收三个 slice 的 9 分量合力；三个 slice 的 advance、force 校验和 worker 响应完成后才提交 global barrier。

该映射是接口资格验证，不是 MATLAB/C++ 数值等价性证明，也不是正式 VIV 统计或锁定区结论。

## 保护与下一步

旧 Stage 1–292 证据、ANCF/EB 核心、物理参数、全局 `dt`、数值阈值和正式协议未修改。Stage 293 已停止，不会自动进入长时间三切片；后续长窗口必须使用新的明确授权、全新 `stage_id/run_id/case_id/runtime`。正式状态仍为 `FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。
