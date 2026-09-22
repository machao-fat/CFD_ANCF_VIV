# HH06 SHM1 Cross-Language Protocol Qualification

## Final gate

```text
classification = PASS_HH06_SHM1_CROSS_LANGUAGE_PROTOCOL
authorized_next_phase = HH06_WORKER_DEPLOYMENT_AND_OFFLINE_RUNTIME_QUALIFICATION
```

本轮没有启动 OpenFOAM、preCICE handshake、`launch.sh` 或 ANCF physical time advance；没有修改 Python protocol、HH06 wrapper、ANCF kernel/source 或 HH06 物理参数，也没有替换 `slice0000` 当前 worker。

## 1. Source and binary identity

构建源是同一明确 Git provenance：

- repository: `https://github.com/machao-fat/CFD_ANCF_VIV.git`
- branch: `feature/ancf-spanwise-hydro-matrix-v1`
- HEAD: `355640e11925b9feddd1a52bb3d93596e5ee8251`
- commit subject: `Connect spanwise hydrodynamic matrices to ANCF state`

构建源文件哈希与先前 SHM1 baseline 一致：

- `ancf_worker_main.cpp`: `83F2D643F855894C8E74AAA11D0C76684E74886FFA0CCFA044B9FB368367DEB9`
- `ancf_kernel.cpp`: `6DDE195A8EA27F253A21D4A859BF41A620697963AB0A834BB9D982B51863AC06`
- `ancf_kernel.hpp`: `C1182AB921D5517C2A5282F8B5FE51C3AB298BEC8B6015BFDCDBCA733C17E22C`

新 binary（未部署）：

```text
D:/研二文件/开题准备/CFD_ANCF_VIV_BUILD/hh06_shm1_qualification_build_exact/cfd_ancf_ancf_kernel_worker_shm1_qualified
size = 2647128 bytes
SHA256 = 69F045EB7F4576E5178D10711F0F265D7458282A7A4ECBCB860A913ADA45BEEF
```

新 binary 原始字节中实际存在 `SHM1` 和 marker `0x314D4853`，与旧 `slice0000` binary 的 unresolved 状态不同。

## 2. Build recipe

使用冻结 commit 内的正式 CMake recipe，编译器为 g++ 11.4.0，CMake 3.22.1，C++17，构建类型 `RelWithDebInfo`，编译参数：

```text
-O2 -g -DNDEBUG -Wall -Wextra -Wpedantic -Werror -std=gnu++17
```

目标只构建 `cfd_ancf_ancf_kernel_worker`；没有修改 recipe、source 或旧 binary。完整 manifest 见 [HH06_SHM1_WORKER_BUILD_MANIFEST.json](HH06_SHM1_WORKER_BUILD_MANIFEST.json)。

## 3. Real HH06 production payload

Python 生产路径保持不变：

```text
HH06 wrapper _build_kernel_model
→ KernelModel
→ KernelStepRequest.payload()
→ encode_kernel_request()
```

region 内容：

```text
s_min = 0.0 m
s_max = 13.12 m
added_mass = [0.616, 0.616, 0.0] kg/m
damping = [0.0, 0.0, 0.0] N s/m²
```

现有 Python payload 证据保持：SHM1 offset 256，marker bytes `53484d31`，version 1，count 1，region bytes 64，region SHA256 `916e2fde1563525d11ee53391493815f691c916cb707f55c45b10a277cb1a87f`。Python protocol 文件未修改，SHA256 仍为 `46719654EF6A283F9E9FFEED602AC2EF3BE560B472E383B691F2DEAB63C1C280`。

## 4. Worker protocol qualification without physical advance

新 binary 实际 initialize ACK：

```text
schema = 1
protocol = 1
message_type = 7
role = cfd_ancf_kernel_worker_v1
return_code after clean shutdown = 0
```

worker wire protocol没有独立 parse-only frame。因此采用源码已有的 pre-advance guard 做真实 binary 解析门：使用生产 payload，仅把 base mass 的一个 off-diagonal 值在审计副本中改为非对称，并重新计算 digest。C++ 先完成：

1. request prefix decode；
2. SPX1/BLS1/可选 SLD1 decode；
3. SHM1 marker/version/count/8-double region decode；
4. DMP1 decode和身份校验（DMP1 fixture）；
5. `validate_model`；
6. model/full contract digest 校验；

随后在 `exactly_symmetric(external_base_mass)` 处返回 17；源码中这一 return 在 `cfd_ancf::advance()` 之前。两种真实 binary 测试均得到预期 return 17、无 step response，因此没有物理时间推进：

| 测试 | ACK | return | 结果 |
|---|---:|---:|---|
| HH06 SHM1 | PASS | 17 | parse/validation guard PASS |
| HH06 SHM1 + DMP1 | PASS | 17 | parse/validation/order guard PASS |
| optional SLD1 + SHM1 + DMP1 | PASS | 17 | full extension order PASS |

这不是把 worker 错误当作数值 PASS；return 17 是预先选择的无物理推进 fail-closed gate。

## 5. Semantic evidence

实际 binary 不是只忽略未知 trailer：若 SHM1 未被解析，后续 model/full contract digest 和 pre-advance guard 路径不会与 production model bytes 对齐。新 binary 对 HH06 SHM1 payload 和 SHM1+DMP1 payload 均进入同一 post-parse guard；同一 source build 的 C++ SHM1 matrix/model/state selftests 全部通过，确认 region 实际连接到湿质量和阻尼矩阵。

legacy 空区域也用新 binary 实测：SHM1 marker absent，initialize ACK PASS，预期 return 17，未推进；Python 原协议 regression 3/3 PASS。

## 6. Deployment boundary

新 binary 仅保存在独立 qualification build 目录，未复制到：

```text
\\wsl.localhost\Ubuntu-22.04\home\machao\OpenFOAM\coupling\singal_slice\slice0000
```

因此当前资格通过，但**尚未获得部署或 preCICE handshake 执行许可**。

## Final status

```text
PASS_HH06_SHM1_CROSS_LANGUAGE_PROTOCOL
AUTHORIZED_NEXT_PHASE = HH06_WORKER_DEPLOYMENT_AND_OFFLINE_RUNTIME_QUALIFICATION
NO_OPENFOAM_RUN = true
NO_PRECICE_HANDSHAKE = true
NO_ANCF_PHYSICAL_ADVANCE = true
NO_NEW_TIME_DIRECTORY = true
OLD_BINARY_OVERWRITTEN = false
```
