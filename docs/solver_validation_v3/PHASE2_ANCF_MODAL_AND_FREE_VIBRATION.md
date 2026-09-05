# Phase 2 — C++ ANCF modal and zero-fluid free-vibration audit

The historical 50 m / 16-element fixture uses `damping_alpha = 0` and
`damping_beta = 0`.  This is not a C++ omission: the source MATLAB model
[`vertical_ttr_case.m`](../../src/structure_ancf_matlab/vertical_ttr_case.m)
also explicitly sets both Rayleigh parameters to zero.  The C++ kernel
currently rejects nonzero damping at its validation boundary, so no damping
sensitivity value was invented or injected for this phase.

The C++ diagnostic is a controlled structural-only experiment:

1. read only the fixture's physical dimensions, material/fluid density,
   tension, time integration parameters and slice positions;
2. recompute the canonical gravity/buoyancy/top-tension load using
   `static_base_load()`;
3. obtain static equilibrium with the same C++ `internal_force_tangent()`;
4. form the transverse-y position/slope subspace used by the retained MATLAB
   modal helper;
5. solve the mass-normalized generalized eigenproblem in C++; and
6. apply a `1e-4 m` first-mode perturbation, set all mapped fluid forces to
   zero, and integrate 20 s at `dt=0.005 s`.

The historical fixture's retained `base_load` is deliberately *not* used as
the static basis: it contains transverse entries and has no separate static
load contract.  It is therefore unsuitable as an unqualified modal reference.

Reproduce after explicitly building the C++ target in WSL:

```powershell
wsl.exe bash -lc 'cmake -S "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/src/coupling/cpp_worker_persistent_ipc_v1" -B "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/solver_validation_v3/ancf_modal_build" -DCMAKE_BUILD_TYPE=Release; cmake --build "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/solver_validation_v3/ancf_modal_build" --target cfd_ancf_ancf_modal_free_diagnostic -j2'
python tools/solver_validation_v3/run_ancf_modal_free.py
python -m unittest tests/solver_validation_v3/test_ancf_modal_free.py
```

The output is new evidence in
`results/ancf_free_decay/undamped/`; historical Stage341–385 files are never
opened for write.  MATLAB was intentionally not started, so a MATLAB/C++
modal numerical-comparison result remains `reference_not_available`.
