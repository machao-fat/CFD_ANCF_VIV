# 过渡模型准备

本轮只读检查 OpenFOAM 10 的 `kOmegaSSTLM` 源码可用性；未运行 kOmegaSSTLM，也未运行 SST 长算。

已记录：kOmegaSSTLM 源文件存在，但没有通过本地 probe 找到可直接复用的 tutorial；未来 pilot 必须先核对模型专用 transition fields、边界条件和初始化。当前推荐为“建议进入”未来独立 transition-model pilot，不代表本轮已完成。

当前 laminar Gate 仍为“不通过”，不得以未运行的 transition model 替代失败的空间/时间证据。
