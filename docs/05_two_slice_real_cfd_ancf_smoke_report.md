# Two-slice real CFD--ANCF smoke report (Stage 4B-v2)

## Decision

**Blocked for this task.** The run was attempted after all mock and protocol
tests passed. It was stopped by the explicit safety rule when the maximum CFL
reached `11.633799` (>0.8). No physical VIV or accuracy conclusion is drawn.

## Attempt configuration

- OpenFOAM: `OpenFOAM-10`
- OpenFOAM process count: 2
- Independent cases: `results/05_multi_slice_integration_tests/real_two_slice/case_slice_0000_retry2` and `case_slice_0001_retry2`
- Protocol: 0.2.1
- `slice_manifest_sha256`: `ffbf9af8cfe8d65d90762fe088c89e4f427c0eb6a010a20741cee788e6437a5d`
- `config_sha256`: `2c8b815b2bf43cd8581e5eeef604a456d7cff8ca77fb0f4ae08978ec28efd9aa`
- Structure: existing persistent ANCF runner through `ProductionANCFAdapter`
- Motion bridge: explicit materialized view for unchanged stage-three
  `ancfFileMotion`; immutable 0.2.1 payloads remained the scheduler source
- Target: two global steps at 0.0025 s and 0.005 s

## Observed result

The first global step completed with a committed checkpoint at 0.0025 s. The
manifest contains both slices, all required CFD fields, case-level
`0/motionScale`, SHA-256 file records, and finite ANCF q/qdot/qddot. The
second-step force output did not become available after the CFD processes
exited with the motion bridge stale. The safety log reports maximum CFL
`11.633799`; the run was not retried.

The preserved machine-readable summary is:

`results/05_multi_slice_integration_tests/real_two_slice_retry2/real_two_slice_closed_loop_summary.json`

The preserved committed first-step manifest is under:

`results/05_multi_slice_integration_tests/real_two_slice_retry2/checkpoints/`

## Static motionScale restart evidence

An independent prescribed-motion restart smoke passed separately:

- OpenFOAM-10, one process;
- `startFrom latestTime`, 0.0025 s to 0.005 s;
- return code 0;
- maximum CFL `0.16794536`;
- static `0/motionScale` hash
  `79ad02083d870f2b39fcbc8d0a9369ad8ff487a88832109d609af01355a330e4`;
- no `motionScale` was fabricated in the final time directory.

This confirms the static-file strategy for the tested case. It does not
convert the failed two-step run into a closed-loop result.

