# Stage186 数值 forensic 修复报告

严格 MATLAB/C++ 双算已修复并通过。step559→step560 单步 prediction/correction 与 40-step 固定 force replay 均在既定误差合同内。

根因是 MSVC 优化下 Newmark predictor 的浮点表达式收缩/舍入路径差异。第 1 次 Newton 的一个自由度出现 1 ulp 差异，被高刚度 ANCF 内力放大；不是物理参数、force mapping 或 internal-force 公式错误。修复为显式分步 volatile double 运算、MSVC /fp:strict，并保持 tangent 四项独立矩阵乘积分组。

step560 修复后 internal_force 最大误差 2.91e-11；40 steps 最大误差：q=2.25514e-17，qdot=4.16334e-15，qddot=4.44089e-12，internal_force=2.67755e-09。

MATLAB 启动 5 次（均为本目标离线导出/验证）；OpenFOAM=0，WSL=0，CFD=0；worker startup=1；owned residual=0。旧证据、旧 runtime、MATLAB 黄金实现、物理核心语义、参数和阈值均未修改。

CMake Release、MSVC /W4、/analyze、compileall、C++ self-tests、专项协议测试和根目录 1179 tests（2 skipped）通过。

Gate：`STAGE4F_D_CPP_WORKER_STRICT_MATLAB_CPP_DUAL_REVIEW_REPAIR_V1_GATE: pass`
`C++_ANCF_NUMERICAL_CORE_STATUS=validated`

本阶段没有启动 CFD；后续若要接入 CFD，仍需新的明确授权。
