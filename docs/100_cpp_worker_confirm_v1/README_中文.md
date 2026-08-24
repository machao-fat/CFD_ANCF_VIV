# Stage100 C++ Worker Confirm V1

本阶段建立独立的 C++ ANCF worker + 持久 stdin/stdout framed IPC coordinator。
当前只完成离线 mock confirm，不把 mock slice 当作真实 OpenFOAM 结果。

## 已验证

- bounded scope：40 global steps，source step 559 -> 560..599，0.05 s，3 slices；
- C++ kernel worker 在整个 segment 只启动 1 次；
- mock slice 各启动 1 次，global barrier 等待三个 slice 全部返回后提交 checkpoint；
- 每条请求/响应保留 schema、run/case、global step、bridge step、time、tick、sequence、request/transaction、producer/consumer、hash、ack 和 finite audit；
- 40/40 physical committed，40/40 fully audited，owned residual=0；
- MATLAB/OpenFOAM/WSL/CFD 真实启动数均为 0；
- source 559、time 2.2075 s、tick 2207500000 等旧证据保持只读。

Stage100 新增两层独立适配：

- `CppKernelCampaignAdapter` 将持久 C++ worker 接到 staged prediction/correction/checkpoint 生命周期；
- `PersistentOpenFOAMSliceAdapter` 和 `Stage100SliceBarrier` 将现有 persistent OpenFOAM slice 协议接到新 barrier。三 slice 只有在 motion、consumed ack、force/load 和 hash/identity 全部通过后才提交 checkpoint。

这些适配器在构造和导入时都不启动外部进程。真实 OpenFOAM/WSL factory 尚未绑定到一次真实合同，因此当前仍不是最终真实 confirm。

## 运行

```powershell
cd "D:\研二文件\开题准备\CFD_ANCF_VIV"
$env:PYTHONPATH="src"
python .\tools\cpp_worker_confirm_v1\run_mock_confirm.py `
  --runtime "D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\cpp_worker_confirm_v1\mock_001" `
  --results "D:\研二文件\开题准备\CFD_ANCF_VIV\results\100_cpp_worker_confirm_v1"
```

真实 OpenFOAM/WSL adapter 尚未接入本 coordinator；因此本 Gate 只证明 worker、IPC、barrier 和审计骨架。新的真实 40-step confirm 仍需要独立 contract、preflight 和明确授权。
