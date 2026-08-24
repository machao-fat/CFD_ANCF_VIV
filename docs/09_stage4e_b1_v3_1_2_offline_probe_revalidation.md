# Stage 4E-B1-v3.1.2 离线探针重判

状态：`passed`。

本阶段没有重新启动 MATLAB 探针。只读读取 v3.1.1 `probe_payload.json`，冻结 SHA-256 为 `140ade450bc1d0227310d6b2fabb388815bdf045e62d8c001b84568146523684`，与期望值一致。源返回码为 `0`，版本为 `9.11.0.2911900 (R2021b) Update 8`，MATLAB 原生 release 为严格 `2021b`。

旧判定失败字段是 `release_R2021b`。修正字段为 `release_2021b`，所有修正检查通过；`matlab_probe_rerun_count=0`，原始证据未修改。
