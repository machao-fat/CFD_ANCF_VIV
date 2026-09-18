# CFD_ANCF_VIV

这是一个面向 CFD–ANCF 耦合、结构动力学、静力/模态验证和后续 VIV 研究的工程与验证仓库。

仓库的核心结构侧程序是 ANCF（Absolute Nodal Coordinate Formulation）有限元模型及其 C++ worker。周边代码提供 case/config 解析、边界条件、截面属性、预应力初始化、Rayleigh 阻尼参数处理、persistent IPC、单/多切片 mapping、preCICE participant glue、OpenFOAM 文件交换和验证证据管理。

本仓库同时保存：

- production source；
- 独立参考解与验证 protocol；
- 数值验证报告、forensic 分析和身份 manifest；
- CFD/ANCF、preCICE 和多切片耦合所需的接口工具；
- cases、references、results、runtime 和 tests。

## 当前基线

结构侧耦合开发基线为：

```text
ANCF_COUPLING_BASELINE_V1
production commit: dfb1a3e7e92220a2e4c9400317de372e637095eb
tag: ancf-coupling-baseline-v1
```

基线文档和完整文件清单：

- [ANCF coupling baseline](docs/baselines/ANCF_COUPLING_BASELINE_V1.md)
- [Baseline manifest](docs/baselines/ANCF_COUPLING_BASELINE_V1_MANIFEST.json)
- [Baseline SHA-256 records](docs/baselines/ANCF_COUPLING_BASELINE_V1_SHA256.txt)

这个 baseline 的含义是：后续受控 CFD–ANCF、单切片、多切片和 preCICE 开发使用固定的结构侧软件身份。它不是“ANCF 已完成完全独立验证”的声明。

当前明确保留的限制是：

- G1 historical V1.2 = `FAIL`；
- G1 current-line V1.1 = `FAIL / G1_STATIC_SOLVE_FAIL`；
- mesh-136 Newton residual plateau 尚未解决；
- `G1_CURRENT_LINE_VALIDATION = NOT_CLOSED`；
- `ANCF_INDEPENDENT_STRUCTURAL_VALIDATION = NOT_CLOSED`；
- CFD、FSI、VIV 和 preCICE 的完整验证仍需独立 protocol。

A–F 当前线验证以及静态求解器终端状态可观测性 V1.2 的状态，以基线清单和对应历史证据为准。

## 分支说明

远端默认分支是 `main`，当前远端 HEAD 为 `298624100d35783c9e2ba6f0d35f4ce8dc408fd2`。`main` 是仓库的主线/集成分支，用于保存被合并到项目主线的稳定历史；它不是自动等同于最新的 validation 分支，也不是某一个 validation protocol 的结果页。

当前仓库中主要分支如下：

| 分支 | 用途 | 当前已知位置 |
|---|---|---|
| `main` | 默认主线、集成历史和对外稳定入口 | `2986241`，tagged `stage4f-d-cpp-physics-ownership-v1-baseline` |
| `validation/baseline-credibility-closure-v1` | ANCF/C++ worker baseline credibility 与相关验证工作 | `36927c0` |
| `validation/g1-terminal-diagnostic-serialization-repair-v1` | G1 terminal diagnostic、observability 后续工作以及 coupling baseline 文档 | `8b9d642` |
| `fix/solver-validation-v3` | solver validation v3 的修复/保留分支 | `832c457` |
| `codex/cpp-worker-comprehensive-audit-repair-v1` | C++ worker comprehensive audit/repair 专项分支 | `ebb0fe5` |

这些专项分支是独立开发/验证线。分支名表示工作主题，不代表该分支已经通过全部 ANCF、CFD、FSI 或 VIV 验证。

### 如何选择入口

- 查看项目主线：`main`。
- 使用冻结的结构侧 coupling baseline：`ancf-coupling-baseline-v1` tag。
- 继续当前 G1 diagnostic/validation lineage：
  `validation/g1-terminal-diagnostic-serialization-repair-v1`。
- 新的 production 改动不得直接覆盖 baseline；应先建立 isolated patch、bounded regression 和新的 focused commit，再创建新的 baseline successor。

从 baseline 创建新的耦合开发分支的示例：

```bash
git fetch origin --tags
git switch -c coupling/<topic> ancf-coupling-baseline-v1
```

## 目录结构

### `src/coupling/`

通用 coupling runtime、mapping、multi-slice orchestration、preCICE contract、checkpoint/restart 和 persistent runner。

关键路径包括：

- `src/coupling/cpp_worker_persistent_ipc_v1/`：C++ ANCF kernel、persistent worker、IPC/wire 支持和公共 API；
- `src/coupling/multi_slice_mapping/`：力、位移、Hermite `H/H^T` mapping、identity 和 virtual-work contract；
- `src/coupling/multi_slice_driver/`：多切片 adapter、scheduler、exchange protocol 和 restart bridge；
- `src/coupling/precice_ancf_adapter_v1/`：ANCF-to-preCICE envelope、barrier、mapping、storage 和 worker adapter。

### `tools/`

验证工具、case 生成器、preCICE participant glue、静力预应力 initializer、阻尼预处理器和受控运行入口。`tools/precice_ancf_adapter_v1/` 是当前 ANCF case/config、kinematics、generic participant、静力预应力和 Rayleigh damping 支持的主要集合。

### `tests/`

单元测试、contract tests、静力/动力验证 harness、wire/API 测试和 bounded regression。测试源码不等于 production implementation，测试结果也必须以对应 protocol 和 manifest 为准。

### `docs/`

验证 protocol、报告、forensic 记录、coupling contract、阶段性决策和 baseline 文档。

### `references/`

独立参考数据、参考实现和文献/benchmark 输入。参考文件的 provenance 和 SHA-256 应在相应 protocol 或 manifest 中记录。

### `cases/`

OpenFOAM、preCICE、单切片、多切片以及其他耦合案例的配置或案例工作区。案例身份不能替代生产基线身份。

### `results/` 与 `runtime/`

数值结果、运行日志、checkpoint、临时 worker 输出和证据材料。它们通常是运行产物，不应通过 `git add .` 批量提交。

## 结构侧生产栈

当前 baseline 冻结的核心结构侧栈包括：

1. C++ ANCF 内核与公共 API；
2. 持久化 C++ worker 以及 IPC/线协议；
3. legacy/explicit 截面属性支持；
4. 通用边界条件、配置和状态身份；
5. 静态预应力初始化器与状态加载器；
6. 结构阻尼与 Rayleigh 阻尼预处理器；
7. 单切片、三切片和通用多切片力/位移映射；
8. ANCF-to-preCICE participant、barrier、storage 和生命周期接口。

每个冻结文件的精确路径、SHA-256、角色和 tracked 状态，以 baseline manifest 为唯一机器可读依据。

## 研究与验证边界

本仓库把以下概念分开管理：

- production implementation identity；
- numerical validation result；
- independent reference provenance；
- coupling protocol readiness；
- CFD/FSI/VIV campaign status。

一次冒烟测试、接口契约测试或耦合就绪性结果，不能自动升级为完整物理验证。任何结论都应同时给出 commit/tag、配置身份、参考来源、适用范围和未闭合限制。

## 变更与提交规则

从 `ANCF_COUPLING_BASELINE_V1` 开始，耦合失败不得通过临时修改 ANCF production source 来绕过。标准流程是：

```text
发现问题
  -> 隔离补丁
  -> 有界回归
  -> 聚焦提交
  -> 新基线版本或明确的基线后继版本
```

提交前应检查：

```bash
git status --short
git diff
git diff --cached
```

不要使用 `git add .` 或 `git add -A` 把 runtime、case、results 和 unrelated untracked 文件一并加入提交。

后续正式 coupling case 至少应记录：

```text
ANCF_BASELINE_TAG
ANCF_BASELINE_COMMIT
ANCF_PRODUCTION_MANIFEST_SHA256
PRECICE_CONFIG_SHA256
STRUCTURAL_CASE_CONFIG_SHA256
OPENFOAM_CASE_IDENTITY / equivalent case manifest
participant source/config identities
slice count and slice length
force dimensional and mapping conventions
motion/displacement mapping convention
```

## 当前工作区说明

README 的加入只补充仓库说明，不改变 ANCF 生产源码、线协议、验证阈值或任何耦合案例。G1、CFD、FSI、OpenFOAM、preCICE 和 VIV 数值算例是否执行，必须由各自明确授权的 protocol 决定。
