# 阶段二 CFD–ANCF 文件式 CSV 协议

版本：`0.1.0`  
适用范围：二维圆柱规定运动、单切片文件交换和阶段一 ANCF 回放。  
更新时间：2026-08-04

## 1. 交换粒度

初期采用“每个耦合步一个完整 CSV 文件”的方式。写文件时先写同目录临时文件，再用原子替换提交；读端只读取已经提交的目标文件。一个快照文件只能对应一个 `time_s`、一个 `step` 和一个 `coupling_iteration`，文件中的行按 `slice_id=0,1,...` 排列。

阶段一已有运动字段保持不变，未改名、未删列。阶段一 MATLAB 接口为 `ancf_write_slice_motion_csv`、`ancf_read_slice_loads_csv`；新增 Python 校验器位于 `src/coupling/file_exchange/csv_contract.py`。

## 2. ANCF → CFD 运动 CSV

| 字段 | 单位/约定 |
|---|---|
| `schema_version` | 字符串，当前 `0.1.0` |
| `step`, `coupling_iteration` | 非负整数 |
| `time_s` | s；同一快照内恒定，跨快照严格递增 |
| `slice_id` | 从 0 开始连续整数 |
| `s_ref_m` | 结构参考弧长，m |
| `x_m,y_m,z_m` | 全局位置，m |
| `vx_mps,vy_mps,vz_mps` | 全局速度，m/s |
| `ax_mps2,ay_mps2,az_mps2` | 全局加速度，m/s² |

规定运动生成器 `generate_prescribed_motion.py` 可生成同一格式的单切片快照。`motion_csv_to_openfoam.py` 会逐个读取和校验快照，并输出 OpenFOAM 可读的时序运动表。当前可复现 ALE 基准仍使用 OpenFOAM 10 的解析 `oscillatingLinearMotion`，运动表用于接口审计和后续自定义运动函数接入；这一区分避免把“解析规定运动”误写成“OpenFOAM 已直接读取 ANCF 文件并自由耦合”。

## 3. CFD → ANCF 载荷 CSV

最少必须有下列字段；转换器还会输出压力、黏性分量、力矩和单位元数据：

| 字段 | 单位/约定 |
|---|---|
| `schema_version`, `step`, `coupling_iteration`, `time_s`, `slice_id` | 与运动端一致 |
| `s_ref_m` | 结构参考弧长，m；必须与 ANCF 模型一致 |
| `force_x_N`, `force_y_N`, `force_z_N` | 传给 ANCF 的积分力，N |
| `force_representation` | 当前为 `integrated_N` |
| `unit_span_m` | 二维 CFD 计算域展向厚度，当前为 1 m |
| `slice_length_m` | 代表结构切片长度，m |
| `pressure_force_*_N` | OpenFOAM 压力力分量，N |
| `viscous_force_*_N` | OpenFOAM 黏性力分量，N |
| `moment_*_Nm` | 力矩，N·m |
| `cfd_time_step_s` | CFD 时间步，s |
| `status` | 完整提交时为 `complete` |

OpenFOAM `forces` 对当前有限展向厚度输出总力，二维单位展向换算明确为

```text
f_2D [N/m] = F_OpenFOAM [N] / unit_span_m [m]
F_slice [N] = f_2D [N/m] * slice_length_m [m]
```

例如 `F_OpenFOAM=10 N`、`unit_span_m=1 m`、`slice_length_m=0.25 m` 时，回传 `F_slice=2.5 N`。转换器只执行一次 `slice_length_m/unit_span_m`；测试 `test_force_conversion_applies_slice_length_once` 已验证不会重复乘长度。

## 4. 自动检查

Python 端检查：文件存在、表头、有限数、时间严格递增、切片编号连续完整、参考弧长一致、同一快照元数据恒定。MATLAB 端现有读取器检查：字段、行数、切片编号、`s_ref_m`、力与元数据有限性及快照内元数据一致性。

已通过的接口测试：

- Python：静止圆柱快照、正弦运动快照、恒定虚拟力、单位换算、错误切片编号、NaN 和非单调时间，共 5 项；
- MATLAB：静止/正弦运动写出，恒定力读取与重复回放，坏文件拒绝；
- MATLAB 实际 CFD 回放：读取 `results/03_prescribed_motion/loads_non_locking.csv` 前 201 个快照，在中部参考位置重复驱动两次，最终响应误差 `0`。

## 5. 提交和失败处理

提交者必须先完整写入临时文件并关闭/刷新，再原子替换目标文件。发现半文件、时间戳回退、切片缺行或 NaN/Inf 时，读端拒绝该文件；当前阶段不使用 socket/MPI，避免通信问题掩盖物理和单位问题。
