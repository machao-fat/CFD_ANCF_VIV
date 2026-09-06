# ANCF_CHECKPOINT_SCHEMA_V1

The C++ adapter checkpoint stores and restores the committed `q`, `qdot`, `qddot`, physical global step/time/tick, source identity, dt, model/mass hashes, boundary contract, and strict numerical-contract lock. Pending predictor/correction state is cleared on restore; it must not survive a rollback.

The persistent worker separately owns request/transaction uniqueness. A parallel-implicit retry repeats a physical window but is a new wire attempt. The new opt-in path preserves physical step/tick while assigning a monotonic non-restored wire sequence and request/transaction IDs. This avoids both duplicate-ID rejection and false multiple-physical-step accounting.

Real worker test: `runtime/parallel_implicit_ancf_rollback_probe_v1_run_004/ancf_rollback_probe.json` saved one checkpoint, completed six identical load trials with five restores, recovered bitwise-identical checkpoint state after every restore, and produced identical trial states. `ANCF_ROLLBACK=PASS`; owned process residual was zero.
