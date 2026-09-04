# Stage 303 接口映射修复

本阶段修复 Stage 302 暴露的耦合接口问题。原 participant 使用 `q[1]`、`q[7]`、`q[13]` 作为三个 CFD slice 的横向位移，而 C++ worker 使用切片位置对应的 ANCF Hermite `H` 矩阵接收载荷。两条路径不是同一个映射。

修复后，结构侧写入 CFD 的位移和速度均由与 C++ `mapping_H3()` 相同的 canonical `H` 行计算；载荷仍由同一 `H^T` 映射送入 C++ worker。每个诊断步还记录接口位置/速度、流体合力、映射合力、流体/结构功率和虚功、刚体力/力矩审计量。

离线验证命令：

```powershell
cd "D:\研二文件\开题准备\CFD_ANCF_VIV"
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s .\tests\stage303_interface_mapping_repair_v1 -v
python -m compileall -q .\src\coupling\stage303_interface_mapping_repair_v1 .\tools\stage303_interface_mapping_repair_v1
python .\tools\stage303_interface_mapping_repair_v1\audit_offline.py
```

离线修复 Gate：

```text
STAGE4F_D_INTERFACE_MAPPING_REPAIR_V1_GATE: pass
```

本阶段没有启动 MATLAB、OpenFOAM、WSL 或 CFD。Stage 302 和所有历史证据只读保护。修复后的真实计算必须使用全新 runtime、run_id、case_id，从 `0 s` 初始场开始；不得把 Stage 302 的 `275 s` 状态作为 restart。
