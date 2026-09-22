# HH06 SHM1 Worker Build Report

## 结果

已从明确的 SHM1 source baseline 构建独立 worker，未覆盖 `slice0000` 当前 binary。

```text
build = PASS
binary = cfd_ancf_ancf_kernel_worker_shm1_qualified
source = feature/ancf-spanwise-hydro-matrix-v1 @ 355640e11925b9feddd1a52bb3d93596e5ee8251
sha256 = 69F045EB7F4576E5178D10711F0F265D7458282A7A4ECBCB860A913ADA45BEEF
deployed = false
```

## Source identity

Git repository: `https://github.com/machao-fat/CFD_ANCF_VIV.git`  
Branch: `feature/ancf-spanwise-hydro-matrix-v1`  
HEAD: `355640e11925b9feddd1a52bb3d93596e5ee8251`  
Commit: `Connect spanwise hydrodynamic matrices to ANCF state`

构建源从该 commit 的 Git blob 原样导出，避免 Windows `core.autocrlf` 改写源文件字节。三个 C++ 文件哈希与此前 SHM1 审计基线完全一致：

- `ancf_worker_main.cpp`: `83F2D643F855894C8E74AAA11D0C76684E74886FFA0CCFA044B9FB368367DEB9`
- `ancf_kernel.cpp`: `6DDE195A8EA27F253A21D4A859BF41A620697963AB0A834BB9D982B51863AC06`
- `ancf_kernel.hpp`: `C1182AB921D5517C2A5282F8B5FE51C3AB298BEC8B6015BFDCDBCA733C17E22C`

## Build recipe

使用仓库正式 `CMakeLists.txt`，没有临时手写简化编译命令：

- CMake 3.22.1
- GNU g++ 11.4.0（Ubuntu 22.04）
- C++17
- `RelWithDebInfo`
- `-O2 -g -DNDEBUG -Wall -Wextra -Wpedantic -Werror -std=gnu++17`
- Linux link 无额外库
- 目标：`cfd_ancf_ancf_kernel_worker`

第一次只导出 worker 子目录时，正式 CMake 配方因声明同级 `cpp_physics_ownership_v1` 而拒绝配置；随后从同一 commit 补齐该 sibling，仍未修改 CMake，最终配置和构建通过。这是构建准备问题，不是源码或 ABI 错误。

## Non-physical worker check

对新 binary 实际启动了两个短生命周期检查：

1. initialize frame → `INITIALIZE_ACK`：schema=1、protocol=1、role=`cfd_ancf_kernel_worker_v1`；
2. shutdown frame → return code 0，clean shutdown；
3. 未发送 kernel step、未调用 `advance(dt)`。

## Real production-payload cross-language guard

使用 HH06 wrapper 的生产 `KernelModel`/`KernelStepRequest` serializer，region 为：

```text
[0.0, 13.12] m
added mass = [0.616, 0.616, 0.0] kg/m
damping    = [0.0, 0.0, 0.0] N s/m^2
```

由于现有 worker wire protocol 没有独立的 parse-only message，本审计使用源码已有的 fail-closed pre-advance guard：

- 生产 serializer 生成 request；
- 仅在审计副本中把 base mass 的一个 off-diagonal 值改为非对称；
- 重新计算 request digest 和外部 contract digest；
- worker 必须先完成 model/SHM1/DMP1 decode、`validate_model` 和 contract digest check，随后在 `exactly_symmetric(external_base_mass)` 处返回 17；
- 源码中 return 17 位于 `cfd_ancf::advance()` 之前，因此没有物理推进。

结果：

| payload | worker ACK | guard return | stdout after request | physical advance |
|---|---:|---:|---:|---:|
| HH06 SHM1 | PASS | 17（预期） | 0 bytes | false |
| HH06 SHM1 + DMP1 | PASS | 17（预期） | 0 bytes | false |
| SLD1 + SHM1 + DMP1 ordering fixture | PASS | 17（预期） | 0 bytes | false |

这不是把 return 17 当作数值通过；它是协议解析完成后、物理 advance 前的受控审计门。

## Extension order

同一生产 serializer 的扩展顺序为：

```text
SPX1 → BLS1 → [optional SLD1] → SHM1 → [optional DMP1]
```

HH06 单切片 `LegacyPointLumped` 正式 payload 没有 SLD1；其实际顺序为 `SPX1 → BLS1 → SHM1`，带 DMP1 的协议 fixture 为 `SPX1 → BLS1 → SHM1 → DMP1`。额外的 piecewise-linear fixture 验证了完整 `SPX1 → BLS1 → SLD1 → SHM1 → DMP1` 顺序。

## Semantic evidence

没有修改 production C++ 增加 debug 接口。语义证据由三部分组成：

1. 新 binary 的实际 pre-advance guard 只在完整 model decode/validation 和 contract digest 通过后返回 17；SHM1 payload 不是被忽略的尾随字节；
2. 同一 binary 对 SHM1+DMP1 和 legacy empty-region request 都通过对应解析路径；
3. 同一冻结 C++ source build 的既有 SHM1 matrix/model/state selftests 全部通过，证明 region 会进入湿质量/阻尼矩阵，而不是静默忽略：
   - matrix selftest: status `PASS`，全部 13 项 PASS；
   - model selftest: `state_mass_connected=true`, `hydro_only_state_damping=true`, `rayleigh_uses_total_mass=true`；
   - state selftest: `canonical_mass=true`, `full_span_mass_scaling=true`, `hydro_only_damping=true`, `static_unaffected=true`。

## Legacy compatibility

用生产 serializer 构造 `hydrodynamic_regions=[]` 的 legacy request；其 SHM1 marker absent。实际新 binary 也到达同一个 pre-advance return 17 guard，且没有 step response 或物理推进。原 Python protocol regression 仍为 `3/3 PASS`。

## Final build qualification

```text
PASS_HH06_SHM1_WORKER_BINARY_QUALIFICATION
authorized_next_phase = HH06_WORKER_DEPLOYMENT_AND_OFFLINE_RUNTIME_QUALIFICATION
```

注意：这是“构建和协议资格”结果，不是部署批准。新 binary 没有替换 `slice0000`，也没有启动 preCICE handshake 或 OpenFOAM。
