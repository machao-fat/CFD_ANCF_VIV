# HH06 SHM1 region scope audit

## 1. 审计边界

本次仅审计 HH06 单切片 wrapper 的 `hydrodynamic_regions` 区间范围和
P1 工件中的物理作用域。没有修改 `kernel_protocol.py`、wrapper、任何
contract 或 CFD case，也没有启动 OpenFOAM、preCICE、ANCF 或创建时间目录。

当前运行状态继续保持：

```text
RUNTIME_BLOCKED_BY_SHM1_WIRE_PROTOCOL_MISMATCH
NO_CODE_CHANGE
NO_RUN
NO_TIME_DIRECTORY
NO_PRECICE
```

审计输入：

| 输入 | 路径 |
|---|---|
| wrapper | `D:\研二文件\开题准备\CFD_ANCF_VIV\tools\hh06_single_slice_structure_0000_participant_v1\structure_0000_participant.py` |
| P1 source contract | `D:\CFD\CFD_ANCF_VIV_reentry_runtime\HH06_P1_WET_MODAL_STRUCTURAL_GATE\source_parameter_contract.json` |
| P1 result | `D:\CFD\CFD_ANCF_VIV_reentry_runtime\HH06_P1_WET_MODAL_STRUCTURAL_GATE\HH06_P1_RESULT.json` |
| HH06 structure contract | `\\wsl.localhost\Ubuntu-22.04\home\machao\OpenFOAM\coupling\singal_slice\slice0000\structure_contract.json` |

## 2. wrapper 当前构造的 SHM1 region

wrapper 的 `_build_kernel_model()` 当前逻辑为：

```python
hydro = bundle.structure["mass"]["added_mass_per_length_kg_m"]
region = region_type(
    0.0,
    float(bundle.structure["geometry"]["length_m"]),
    tuple(float(v) for v in hydro),
    (0.0, 0.0, 0.0),
)
```

因此当前实际构造为：

```text
s_min = 0.0 m
s_max = L = 13.12 m
added_mass_per_length = [0.616, 0.616, 0.0] kg/m
linear_damping_per_length = [0.0, 0.0, 0.0] N*s/m^2
```

即 **A：SHM1 added-mass region 覆盖全长 0--13.12 m**。当前 wrapper
没有把 `5.94 m` 作为 SHM1 region 的截断点。

## 3. HH06 流区/静水区边界

本轮合同给出的分区为：

| 区间 | 物理描述 |
|---|---|
| `0--5.94 m` | 流区 / stepped-current boundary 以内 |
| `5.94--13.12 m` | 静水区 |

P1 `source_parameter_contract.json` 中对应字段为：

```json
"occupancy": {
  "whole_riser_submerged": true,
  "interval_m": [0.0, 13.12],
  "stepped_current_boundary_m": 5.94,
  "used_in_p1": false
}
```

这说明 `5.94 m` 在 P1 artifact 中被记录为 stepped-current 分界，且明确
标记为 `used_in_p1: false`；P1 的湿结构模态/时域合同没有把它用作湿质量
region 的截断边界。

## 4. P1 wet-mass 证据

P1 source contract 的 `hydro_region` 为：

```json
{
  "s_min_m": 0.0,
  "s_max_m": 13.12,
  "added_mass_per_length_kg_m": [0.616, 0.616, 0.0],
  "linear_damping_per_length_Ns_m2": [0.0, 0.0, 0.0]
}
```

P1 artifact 同时给出：

```text
structural line mass        = 1.845 kg/m
added mass per length       = 0.616 kg/m (x/y)
wet transverse line mass    = 2.461 kg/m
global added mass in x/y    = 8.08192 kg
```

其中：

```text
0.616 kg/m * 13.12 m = 8.08192 kg
```

该数值与 **全长** SHM1 region 完全一致。若改为仅覆盖静水区
`5.94--13.12 m`，全局 added mass 将变为：

```text
0.616 * (13.12 - 5.94) = 4.42288 kg
```

这与 P1 artifact 的 `global_added_mass_xy_kg = 8.08192` 不一致；若改为
仅覆盖流区，则同样不能复现 P1 wet-mass 数值。

## 5. HH06 structure contract 对照

当前 `structure_contract.json` 明确声明：

- 模型来源为 `P1 validated ANCF wet structural model`；
- `mass_per_length_kg_m = 1.845`；
- `added_mass_per_length_kg_m = [0.616, 0.616, 0.0]`；
- P1 added-mass field 必须 **included exactly once**；
- `global_added_mass_xy_kg = 8.08192`；
- `global_wet_transverse_mass_kg = 32.28832`；
- `stepped-current` 分界没有被写入 SHM1 scope。

因此当前 HH06 structure contract 与 wrapper 的全长 region 是相互闭合的。

## 6. added mass 与 damping 的最终 scope 判断

### 6.1 Added mass

**本次 HH06 P1 runtime 应采用 A：全长 `0--13.12 m`。**

理由不是把流区和静水区混为一谈，而是：

1. P1 合同定义的是整根浸没结构的 wet structural model；
2. `whole_riser_submerged=true` 且 occupancy interval 是全长；
3. P1 hydro region 明确给出全长 `[0, 13.12]`；
4. P1 global added mass 数值只能由全长 `0.616 kg/m` 得到；
5. `5.94 m` 在 P1 中是 stepped-current boundary，且 `used_in_p1=false`。

静水区仍是浸没流体环境；“静水”表示来流速度条件，不等于没有流体
排开体积和 added mass。若以后建立“局部流速相关 added mass”模型，应新增
独立、明确的分段物理合同，不能把当前 P1 artifact 擅自改成静水区-only。

### 6.2 Linear damping

当前 P1 wet modal/TD2/TD4 合同的线性水动力阻尼是：

```text
[0.0, 0.0, 0.0] N*s/m^2
```

因此在当前 case 中，scope 选择不会改变数值：全长 region 和静水区-only
都会得到零阻尼。但为了保持 wire/schema 与 P1 物理合同清晰，仍应把它记录
在同一个全长 `[0, 13.12]` SHM1 region 中，而不是用 region 截断来表达“零”。

## 7. 结论：A 还是 B

```text
SHM1_ADDED_MASS_SCOPE       = A_FULL_LENGTH_[0,13.12]m
SHM1_DAMPING_SCOPE          = FULL_LENGTH_RECORD_WITH_ZERO_COEFFICIENT
5.94m_BOUNDARY_ROLE         = STEPPED_CURRENT_BOUNDARY_ONLY
P1_USED_5.94m_AS_HYDRO_CUT  = FALSE
```

本审计不建议将 SHM1 改为 B（仅 `5.94--13.12 m` 静水区）。B 会破坏 P1
wet-mass 数值闭合，并将一个尚未在 P1 中定义的“局部水动力作用域”误写成
已验证结构合同。

## 8. 与单切片映射的关系

本结论只针对 ANCF 内部 SHM1 wet structural region。它不改变单切片
preCICE 空间映射：

- 结构内部仍为 `Ne=32`、33 nodes、198 DOF；
- 耦合点仍为 `s=2.97 m`；
- `DeltaL=1.98 m` 的 CFD strip resultant force 只转换一次；
- CFD 200 个面中心不与 ANCF 节点一一对应。

## 9. 输入身份哈希

| 文件 | SHA256 |
|---|---|
| `source_parameter_contract.json` | `72FEFE360DEC441484D2E8F7DA57E1C09D66CAB9F943DD072D13929F10EDA90C` |
| `HH06_P1_RESULT.json` | `11A6AA187BE8637A7656C6F6451E7E4FC6398F2B3DAC4D56EE1B3C5056E9343F` |
| `structure_contract.json` | `6140027D309358C787798D81916417BF33730F7B8A8D47A02619FA35C26E0A24` |
| `structure_0000_participant.py` | `7527495AAFC00E0198710D43D67008C988E069C60EFA6288A88FDEEE20471286` |

## 10. 审计后状态

本轮只读审计没有解除 SHM1 wire blocker。Python codec 仍未实现，故：

```text
RUNTIME_BLOCKED_BY_SHM1_WIRE_PROTOCOL_MISMATCH
NO_CODE_CHANGE
NO_RUN
NO_TIME_DIRECTORY
NO_PRECICE
```

如果后续要补齐协议，只能在单独授权后让 Python serializer 发送与本报告
一致的全长 SHM1 region；本轮不执行该修改。
