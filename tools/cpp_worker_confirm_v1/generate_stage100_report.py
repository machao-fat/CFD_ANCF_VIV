from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    results = project / "results" / "100_cpp_worker_confirm_v1"
    gate = json.loads((results / "stage4f_d_cpp_worker_confirm_v1_gate.json").read_text(encoding="utf-8"))
    result = json.loads((results / "mock_confirm_result.json").read_text(encoding="utf-8"))
    report = f"""# Stage100 C++ Worker Confirm V1 报告

## 结论

`{gate['gate']}`

这是离线 mock integration Gate，不是真实 OpenFOAM/WSL CFD Gate。C++ kernel worker 在一个 segment 内只启动一次，三 个 mock slice 各启动一次，40/40 physical committed、40/40 fully audited，owned residual=0。

## 测量

- mock segment wall-clock：`{result['wall_clock_s']:.9f} s`
- C++ worker startup：`{result['worker_start_count']}`
- slice startup：`{result['slice_start_counts']}`
- target global steps：`{result['committed'][0]['global_step']} -> {result['committed'][-1]['global_step']}`
- real MATLAB/OpenFOAM/WSL/CFD starts：`0/0/0/0`

## 协议审计

- source mapping：step `559`、time `2.2075 s`、tick `2207500000`；
- case-local bridge step：`1..40`；target time/tick 连续；
- duplicate、stale、out-of-order、identity mismatch、NaN/Inf：均为 0；
- 三 slice barrier release：40 次；checkpoint lineage 连续。

## 保护与风险

本阶段没有修改 Stage 1--96 证据、MATLAB worker 基线、ANCF/EB 核心、物理参数、global dt、slice 数量、数值阈值或正式 0.2.1 协议。旧 runtime 仍只读。

Stage100 已增加现有 `PersistentOpenFOAMSliceProcess` 的独立生命周期适配器，并完成 fake-backend 离线验证；但真实 OpenFOAM/WSL factory 尚未接入本次新 coordinator 的执行合同。因此不能把本 Gate 当作真实 CFD 资格，也不能据此宣称 MATLAB/C++ 生产替换完成。下一步真实 confirm 需要新的 stage/run/case/runtime、独立 contract/preflight、production factory wiring，以及对 OpenFOAM、WSL 和 CFD 的明确授权。

## 技能与工具

实际使用：`cfd-ancf-viv-cpp-worker-audit`、CMake/MSVC 已有构建产物、Python unittest、compileall、离线 mock/fault injection。

候选的 VTune/AMD uProf、外部 static-analysis/QE 专用 skill 未安装或未调用；没有自动安装外部 skill。此次没有启动 MATLAB，因为本阶段无需真实数值 probe；用户授权不扩大为 OpenFOAM/WSL/CFD 授权。

## 统计状态

- `frequency=not_evaluable_cpp_confirm_only`
- `FORMAL_STROUHAL_STATUS=not_completed`
- `STABLE_VIV_RESPONSE_CLAIM=not_completed`
- `LOCK_IN_CLAIM=not_completed`
"""
    (results / "stage100_cpp_worker_confirm_v1_report.md").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
