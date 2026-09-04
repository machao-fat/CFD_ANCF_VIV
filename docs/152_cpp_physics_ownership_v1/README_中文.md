# Stage 152 C++ 物理所有权迁移

本阶段把结构侧物理计算迁移到独立的 C++ ownership worker target。旧 MATLAB worker、旧 persistent IPC target、Stage 1--151 证据和旧 runtime 继续只读保护。

## 构建

使用 MSVC 2022 x64 和 CMake 3.31.6，在 Visual Studio x64 开发者环境中构建：

```powershell
cmake --build "runtime/cpp_worker_persistent_ipc_v1/build-release" --target cfd_ancf_physics_ownership_selftest cfd_ancf_physics_ownership_worker cfd_ancf_physics_ownership_worker_double_solve --config Release --parallel 4
```

## 离线验证

```powershell
python "tools/cpp_physics_ownership_v1/run_offline_validation.py" `
  --worker "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_physics_ownership_worker.exe" `
  --steps 40 `
  --output "results/152_cpp_physics_ownership_v1/offline_40step_worker_audit.json"

python "tools/cpp_physics_ownership_v1/run_fault_injection.py" `
  --worker "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_physics_ownership_worker.exe" `
  --output "results/152_cpp_physics_ownership_v1/failure_injection_audit.json"
```

这些命令只启动本地 C++ worker，不启动 MATLAB、OpenFOAM、WSL 或 CFD。

## 物理合同

```text
Q_base = Q_body_gravity + Q_body_buoyancy + Q_top_tension
Q_ext  = Q_base + Q_static_initialization + Q_cfd
```

运行时 force representation 固定为 `integrated_N`。`line_Npm` 只能通过显式正 slice 长度转换。请求中的第四个状态向量不再是 MATLAB 生成的总 `base_load`，而是可审计的静态初始化载荷；gravity、buoyancy 和 top tension 由 C++ 根据模型参数组装。

## 结果

独立证据位于 `results/152_cpp_physics_ownership_v1`。最终 Gate 和中文报告分别为：

- `independent_gate.json`
- `docs/152_cpp_physics_ownership_v1/最终报告_中文.md`

本阶段未启动真实 CFD；即使 Gate 通过，后续真实 confirm 仍需要新的明确授权。
