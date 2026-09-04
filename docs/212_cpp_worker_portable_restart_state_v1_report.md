# C++ Worker Portable Restart State V1

Gate: `STAGE4F_D_CPP_WORKER_PORTABLE_RESTART_STATE_V1_GATE: pass`

## Result

Every newly committed C++ worker barrier checkpoint can now contain
`checkpoint_metadata.ancf_restart_state` with the portable schema
`ancf_portable_restart_state_v1`. It stores the corrected `q`, `qdot`, and
`qddot`, source identity, current and next applied 3-by-3 slice loads, model
and mass-matrix identities, finite-value audit, parent checkpoint hash, and
a canonical state hash.

The state is prepared after correction and before the barrier commit. The
barrier writes it to a temporary checkpoint, fsyncs it, finalizes the owned
participants, and only then atomically renames a `committed` checkpoint.
An aborted transaction therefore has no visible accepted restart state.

## Restart Use

For a new, explicitly authorized segment, provide the accepted committed
checkpoint and its SHA-256 to `CppKernelCampaignAdapter.from_checkpoint(...)`
with a new `run_id`, `case_id`, and runtime. The adapter verifies the state
hash, checkpoint identity, model hash, mass-matrix hash, finite values, and
force shape, then permits only `global_step + 1` as bridge step 1.

The production runner accepts both formats:

- historical reconstructed source: root `structure` and
  `applied_slice_forces_N`;
- new portable barrier checkpoint: metadata restart `structure` and the
  committed `next_applied_slice_forces_N`.

This preserves the causal load convention: a restarted next step uses the
previous checkpoint's next applied force rather than its old correction force.

## Stage 211 Boundary

Stage 211 was deliberately not rewritten. Its final checkpoint at step 1439
has SHA-256 `17d71a2a0f03dae04d57f1afbade7299842c1e0bdf633a3b92ff070ecaf982d3`
and has no embedded restart state, so its first continuation still requires
the existing one-time recovery/replay route. Every checkpoint produced after
this feature is active can be resumed directly without replaying prior force
logs.

## Verification

- `python -m compileall -q src\\coupling\\cpp_worker_confirm_v1 tools\\cpp_worker_confirm_v1`: pass.
- `python -m unittest discover -s tests\\cpp_worker_confirm_v1 -v`: 80 passed.
- Root `python -m unittest discover -q`: pass.
- Real process starts: MATLAB=0, OpenFOAM=0, WSL=0, CFD=0; owned residual=0.

No ANCF/EB core, physical parameter, numerical threshold, slice topology,
global time step, or formal 0.2.1 protocol semantics were changed. Stage75,
E5-C, larger slice counts, long-time VIV, lock-in, and experiments were not
started. A new real segment still requires a new explicit authorization.
