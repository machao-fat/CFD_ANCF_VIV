# Phase A environment and source identity

* MATLAB reference: `D:\Program Files\MATLAB\R2021b\bin\matlab.exe`, reported
  version `9.11.0.2911900 (R2021b) Update 8`.
* C++ compiler: `g++ (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0`.
* Located 50 m / 16-element fixture:
  `runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json`;
  SHA-256 `b77685eeff1582ceba589809889fcb63df74ed9f11c4075a5df5307fd014d5d2`.
* Fixture role: its geometry/material/fluid/top-tension/Newmark fields were
  independently frozen in the cross-run contract.  Its historical `base_load`
  was intentionally not consumed; both implementations rebuilt static load
  from the same physical model.
* Exact MATLAB-script, C++ kernel and C++ diagnostic SHA-256 values are stored
  in `phase_a_result.json` under `sources`.
* This audit was recorded on Git commit
  `3a84d614d685aaeeb4cbca28c0874c5146f2f98f` before the present metadata-only
  commit.  The original MATLAB source was not modified.
