# HH06 qualified worker deployment report

## Deployment result

The previously qualified SHM1-capable worker was copied to the HH06
`slice0000` case under an independent filename.  The legacy worker was not
overwritten or deleted.

| item | value |
|---|---|
| source | `D:/研二文件/开题准备/CFD_ANCF_VIV_BUILD/hh06_shm1_qualification_build_exact/cfd_ancf_ancf_kernel_worker_shm1_qualified` |
| deployed WSL path | `/home/machao/OpenFOAM/coupling/singal_slice/slice0000/cfd_ancf_ancf_kernel_worker_shm1_qualified` |
| deployed SHA256 | `69F045EB7F4576E5178D10711F0F265D7458282A7A4ECBCB860A913ADA45BEEF` |
| deployed size | 2,647,128 bytes |
| source branch | `feature/ancf-spanwise-hydro-matrix-v1` |
| source HEAD | `355640e11925b9feddd1a52bb3d93596e5ee8251` |
| previous worker | `/home/machao/OpenFOAM/coupling/singal_slice/slice0000/cfd_ancf_ancf_kernel_worker` |
| previous worker SHA256 | `7B246C53F2040CE9DCBA3100700E1D5DEF905E84D8452F560B6D1B29E88D8473` |
| previous worker overwritten | **No** |

The independent runtime selector is
`HH06_WORKER_QUALIFIED_RUNTIME.json`; it points Structure_0000 to the new
binary without changing the preCICE XML or the legacy launch target.

## Frozen source identity

The binary was built from the exact Git-blob export of the frozen commit, not
from a mixed working tree:

- `ancf_worker_main.cpp`: SHA256
  `83F2D643F855894C8E74AAA11D0C76684E74886FFA0CCFA044B9FB368367DEB9`
- `ancf_kernel.cpp`: SHA256
  `6DDE195A8EA27F253A21D4A859BF41A620697963AB0A834BB9D982B51863AC06`
- `ancf_kernel.hpp`: SHA256
  `C1182AB921D5517C2A5282F8B5FE51C3AB298BEC8B6015BFDCDBCA733C17E22C`

Build recipe and complete provenance remain in
`HH06_SHM1_WORKER_BUILD_MANIFEST.json`.

## Scope boundary

Deployment itself performed no OpenFOAM solve, no preCICE initialization, no
Fluid_0000 operation, no ANCF physical step, and no creation of an OpenFOAM
time directory.  The offline physical-step qualification is reported
separately.
