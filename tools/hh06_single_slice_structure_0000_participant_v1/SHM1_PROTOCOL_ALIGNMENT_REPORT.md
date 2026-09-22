# SHM1 protocol alignment report

## 审计范围与结论

本报告是对 HH06 `Structure_0000` 单切片 runtime 当前 SHM1（spanwise
hydrodynamic-region）线协议的离线只读审计。审计对象为：

- C++ worker source：`\\wsl.localhost\Ubuntu-22.04\home\machao\OpenFOAM\coupling\singal_slice\slice0000\ancf_worker_main.cpp`
- C++ kernel headers/source：同目录的 `ancf_kernel.hpp`、`ancf_kernel.cpp`
- Python protocol：`D:\研二文件\开题准备\CFD_ANCF_VIV\src\coupling\cpp_worker_persistent_ipc_v1\kernel_protocol.py`

当前结论：

```text
RUNTIME_BLOCKED_BY_SHM1_WIRE_PROTOCOL_MISMATCH
NO_RUN
NO_TIME_DIRECTORY
NO_PRECICE
```

C++ worker/source 已具备 SHM1 解码和矩阵组合能力；当前 Python
`kernel_protocol.py` 尚未声明、校验或序列化 SHM1。因此 HH06 wrapper
必须继续 fail-closed，不能在未对齐时静默发送一个不带湿质量扩展的模型。

本轮没有修改 C++、Python、wrapper、contract 或 CFD case；没有执行
`launch.sh`、`preCICE.initialize()`、OpenFOAM、ANCF 或任何时间推进。

## A. C++ 当前协议

### A.1 数据结构

`ancf_kernel.hpp` 定义了：

```cpp
struct SpanwiseHydrodynamicRegion {
  double s_min_m;
  double s_max_m;
  std::array<double, 3> added_mass_per_length_kg_m;
  std::array<double, 3> linear_damping_per_length_Ns_m2;
};
```

字段语义为：

| 顺序 | 字段 | 类型 | 单位/含义 |
|---:|---|---|---|
| 1 | `s_min_m` | `double` | 参考坐标区间下界，m |
| 2 | `s_max_m` | `double` | 参考坐标区间上界，m |
| 3--5 | `added_mass_per_length_kg_m[0:2]` | 3 × `double` | 全局 ANCF x/y/z 分量，kg/m |
| 6--8 | `linear_damping_per_length_Ns_m2[0:2]` | 3 × `double` | 全局 ANCF x/y/z 分量，N·s/m² |

`Model` 持有 `std::vector<SpanwiseHydrodynamicRegion>
hydrodynamic_regions`。系数不是 CFD 面或 ANCF 节点逐一配对，而是参考坐标区间上的常值线密度，随后由 kernel 在 ANCF 单元上进行区域积分。

### A.2 marker、version 和数量上限

`ancf_worker_main.cpp` 当前常量为：

```text
SPANWISE_HYDRODYNAMIC_EXTENSION_MARKER  = 0x314D4853
SPANWISE_HYDRODYNAMIC_EXTENSION_VERSION = 1
MAX_SPANWISE_HYDRODYNAMIC_REGIONS      = 10000
```

在目标部署的小端机器上，marker 的字节表示为 `53 48 4D 31`，即
ASCII `SHM1` 的 little-endian `uint32` 表示。

### A.3 SHM1 wire layout

SHM1 是可选的 model trailer，不改变历史基础模型字段。其 wire layout
为（小端）：

```text
header:  <III
         marker, version, region_count

per region: <8d
            s_min_m, s_max_m,
            added_mass_x, added_mass_y, added_mass_z,
            damping_x, damping_y, damping_z
```

因此：

- header 长度：`3 * sizeof(uint32_t) = 12` bytes；
- 每个 region 长度：`8 * sizeof(double) = 64` bytes；
- SHM1 payload 长度：`12 + 64 * region_count` bytes。

worker 使用 `take()` 对 payload 做边界检查后 `memcpy` 到 native
`uint32_t`/`double` 对象。当前 Windows/WSL x86-64 部署按 little-endian
解释；Python codec 必须显式使用 `<III` 和 `<8d`，不能依赖 Python/native
默认字节序。

### A.4 trailer 顺序

当前 C++ 解码顺序为：

```text
历史基础 model layout
 -> SPX1（可选显式截面属性）
 -> BLS1（可选 model-static base load）
 -> SLD1（可选分布式外载元数据）
 -> SHM1（可选 spanwise hydrodynamic regions）
 -> DMP1（request-level Rayleigh damping extension）
```

源码明确注明 SHM1 必须位于 request-level DMP1 之前。没有 SHM1 marker
时，worker 保持空的 `hydrodynamic_regions`；这意味着 absence 不是一个
“自动使用 HH06 湿质量”的隐式默认值。

### A.5 C++ 校验和物理组合

worker 在读取 SHM1 时检查：

1. header 和每个 region 的剩余字节足够；
2. `version == 1`；
3. `region_count <= 10000`；
4. 所有 region 数据可完整读取。

随后 `ancf_kernel.cpp` 的 model validation 继续检查：

- `0 <= s_min < s_max <= model.length_m`；
- region 按 `s_min` 排序且不能有正测度重叠；
- 添加质量和阻尼系数有限且非负。

kernel 对 region 进行 Gauss-5 区间积分，将添加质量矩阵加到外部基础质量
上一次，将线性水动力阻尼加到总阻尼上一次。SHM1 添加质量不进入静态基础载荷，因而不会改变静力平衡定义。C++ worker 源码还明确要求外部基础质量必须是未预先加湿质量的 base matrix，避免 double counting。

## B. Python 当前协议

### B.1 当前已支持的 extension

当前 `kernel_protocol.py` 已声明和/或序列化：

| extension | 当前状态 | 作用 |
|---|---|---|
| `EXL1` | 已支持 | 扩展布局、边界和质量积分阶数 |
| `SPX1` | 已支持 | 显式 `EA/EI/mass/displaced area` |
| `BLS1` | 已支持 | model-static base-load 来源 |
| `SLD1` | 已支持 | piecewise-linear distributed external load 元数据 |
| `DMP1` | 已支持 | request-level Rayleigh damping |
| `SHM1` | **缺失** | spanwise added mass/linear damping |

`KernelModel` 当前字段包含 SLD1、SPX1 和 BLS1 相关字段，但没有
`hydrodynamic_regions` 或等价 SHM1 字段。`KernelModel.validate()` 也没有
SHM1 区间、系数、数量上限或有限性校验。

### B.2 当前 Python 序列化顺序

`KernelModel.bytes()` 当前会构造基础 model bytes，然后按条件追加：

```text
SPX1（如启用显式截面属性）
BLS1（如启用 model-static base load）
SLD1（如启用 distributed load）
return model_bytes
```

`KernelStepRequest.payload()` 随后在 model bytes 之后追加 request-level
DMP1（以及已有 request arrays/identity 数据）。当前没有 SHM1 append
分支。因此即使 HH06 wrapper 在结构 bundle 中已有湿质量数据，当前
Python model bytes 也无法表达它。

### B.3 当前 Python 缺少的 SHM1 内容

至少缺少以下 codec 层内容：

1. `SPANWISE_HYDRODYNAMIC_EXTENSION_MARKER = 0x314D4853`；
2. `SPANWISE_HYDRODYNAMIC_EXTENSION_VERSION = 1`；
3. `MAX_SPANWISE_HYDRODYNAMIC_REGIONS = 10000`；
4. `SpanwiseHydrodynamicRegion` 数据类或等价不可变记录；
5. 每个 region 的 8 个 wire double 字段；
6. `KernelModel.hydrodynamic_regions` 字段；
7. SHM1 区间排序、非重叠、范围、有限性和非负系数校验；
8. `KernelModel.bytes()` 中位于 SLD1 之后、DMP1 之前的 `<III` + `<8d` 序列化；
9. malformed/truncated/unknown-version/over-limit fixture 校验。

当前 Python 不支持 SHM1 并不是“没有数据时的正常 dry-run 状态”：对于
HH06 wet structural contract，它是阻断项。wrapper 已经使用 capability
check 拒绝静默回退到没有水动力添加质量的 model。

## C. 差异与风险

| 项目 | C++ worker/kernel | Python protocol | 影响 |
|---|---|---|---|
| marker/version | SHM1 v1 已实现 | 无常量 | Python 无法生成可识别 trailer |
| region 数据结构 | 8 doubles/region | 无字段 | 无法携带区间和系数 |
| region count | 上限 10000 | 无检查 | 无法在发送端 fail-closed |
| byte order | raw `memcpy`，当前 x86-64 小端 | 无 SHM1 pack | 需要显式 `<` codec |
| trailer 顺序 | SHM1 在 SLD1 后、DMP1 前 | 仅 SLD1 后直接 return | DMP1 后无法补救 model trailer 顺序 |
| matrix semantics | worker/kernel 一次组合湿质量/阻尼 | 未表达 | 可能漏加或无法审计 wet mass |
| failure behavior | C++ 无 SHM1 时接受空 hydro regions | Python 当前不发送 SHM1 | 若不 fail-closed，会误跑干结构/基础质量合同 |

关键风险不是 force mapping 或 ANCF kernel 数学实现，而是“发送端没有
把 HH06 湿质量合同编码到 worker 已期待的 SHM1 wire ABI”。因此当前状态
必须保留为 `RUNTIME_BLOCKED_BY_SHM1_WIRE_PROTOCOL_MISMATCH`。

## D. 最小修改文件列表（本轮不执行）

### D.1 必需修改

```text
D:\研二文件\开题准备\CFD_ANCF_VIV\src\coupling\cpp_worker_persistent_ipc_v1\kernel_protocol.py
```

该文件需要增加 SHM1 constants、region record、validation、`KernelModel`
字段和 trailer serialization。HH06 wrapper 已按 `hydrodynamic_regions`
能力检查并构造一条覆盖 `s=0..L` 的 region，因此在 codec 对齐后不需要
为了 SHM1 再改 wrapper 的物理数据流。

### D.2 建议增加的离线协议测试（实现阶段）

在现有 Python protocol test/fixture 位置增加 SHM1 专用测试，至少覆盖：

- marker/version/region count 的 byte-exact 位置；
- 一条 region 的 `<8d` 顺序和单位字段；
- 多 region 排序、相切允许、重叠拒绝；
- NaN/Inf、负系数、越界区间、过大 count 拒绝；
- SHM1 与 SLD1、DMP1 同时存在时的 trailer 顺序；
- C++ worker 期望长度与 Python payload 长度一致。

测试文件的具体路径应在实现阶段按仓库现有测试布局确定；本报告没有
创建或修改测试文件。

### D.3 不需要修改的文件

在当前目标 C++ source 已经确认 SHM1 v1 的前提下，最小修复不应修改：

- `ancf_kernel.cpp`；
- `ancf_kernel.hpp`；
- `ancf_worker_main.cpp`；
- HH06 物理参数、结构合同和 mapping contract；
- OpenFOAM、preCICE XML 或 CFD case。

若实现阶段发现实际运行 binary 与上述 source 不是同一 SHM1-capable build，
应停止并单独做 binary/source identity audit，而不是改协议字段或绕过检查。

## E. 是否影响 ANCF kernel ABI

### E.1 C++/kernel ABI

**不影响当前 ANCF kernel 的函数 ABI。** SHM1 解码已经位于 worker 的
model-payload 解析层；`ancf_kernel.hpp` 的 `SpanwiseHydrodynamicRegion`
和 `Model::hydrodynamic_regions` 也已经存在。后续仅补齐 Python wire
serializer，不需要修改 kernel 函数签名、ANCF element、Newton 求解器或
静态平衡算法。

### E.2 wire ABI

**会影响 Python→worker 的 model payload wire ABI，但属于已经冻结的可选、
版本化 append-only SHM1 扩展。** 对没有 SHM1 的旧模型，历史 payload
布局仍可保持；对 HH06 wet contract，发送端必须显式追加 SHM1 v1。该变化
不是 preCICE API 变化，也不是 CFD force/displacement interface 变化。

### E.3 物理语义约束

SHM1 的 added mass/damping 必须由 contract 明确给出，并且 C++ worker
接收的是未预加湿质量的 external base mass。不得在 Python、worker、kernel
三处重复加同一项，也不得为了通过协议检查把 SHM1 字段填成任意零值。

## 审计证据摘要

| 文件 | SHA256（本次只读扫描） |
|---|---|
| `\\wsl.localhost\Ubuntu-22.04\home\machao\OpenFOAM\coupling\singal_slice\slice0000\ancf_worker_main.cpp` | `83F2D643F855894C8E74AAA11D0C76684E74886FFA0CCFA044B9FB368367DEB9` |
| `\\wsl.localhost\Ubuntu-22.04\home\machao\OpenFOAM\coupling\singal_slice\slice0000\ancf_kernel.hpp` | `C1182AB921D5517C2A5282F8B5FE51C3AB298BEC8B6015BFDCDBCA733C17E22C` |
| `\\wsl.localhost\Ubuntu-22.04\home\machao\OpenFOAM\coupling\singal_slice\slice0000\ancf_kernel.cpp` | `6DDE195A8EA27F253A21D4A859BF41A620697963AB0A834BB9D982B51863AC06` |
| `D:\研二文件\开题准备\CFD_ANCF_VIV\src\coupling\cpp_worker_persistent_ipc_v1\kernel_protocol.py` | `89735D288A9DE72D81FDB203D8952665A6720ADC1A17E6534667966990AD243F` |

以上 hash 仅用于本次报告的输入身份记录；没有生成 binary、没有执行编译、
没有启动任何 runtime。

## 最终状态

```text
SHM1_CPP_WORKER_PROTOCOL = PRESENT_V1
SHM1_PYTHON_CODEC         = MISSING
ANCF_KERNEL_ABI_CHANGE    = NOT_REQUIRED
RUNTIME_STATUS             = RUNTIME_BLOCKED_BY_SHM1_WIRE_PROTOCOL_MISMATCH
NO_RUN                     = TRUE
NO_TIME_DIRECTORY          = TRUE
NO_PRECICE                 = TRUE
```

在人工批准并单独授权“只补齐 Python SHM1 codec”之前，不应进行
preCICE handshake dry-run 或任何 ANCF/CFD 计算。
