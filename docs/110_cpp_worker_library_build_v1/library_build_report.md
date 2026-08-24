# Fresh OpenFOAM Library Build Preparation

本阶段只完成 fresh stage-local 构建准备和授权门控，没有执行 WSL、OpenFOAM 或 CFD。

- 新 runtime：`runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_004`
- 新结果：`results/110_cpp_worker_library_build_v1`
- 源码文件：7 个，均记录 SHA-256；Windows 下 `lnInclude` reparse link 已物化为普通文件
- 目标输出：`fresh_library_build_004/lib/libancfFileMotion.so`
- 旧 runtime/旧 `.so`：明确禁止复用
- dry-run：通过；`--execute` 缺少授权时：启动 WSL 前 fail-closed
- fresh library guard：4/4
- execution guard：2/2
- staging 回归：3/3
- persistent IPC：15/15
- C++ confirm 专项：39/39
- 根目录 unittest：1084 passed，1 skipped，0 failure/error（1085 collected）
- compileall：通过
- MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0
- owned residual：0

当前 Gate：

`STAGE4F_D_CPP_WORKER_LIBRARY_BUILD_V1_GATE: do_not_pass`

原因是尚未获得明确的 OpenFOAM/WSL/CFD 真实执行授权，因此 fresh `.so` 尚未构建。构建脚本默认 dry-run，只有显式 `--execute` 与授权 token 同时提供时才会调用 WSL。
