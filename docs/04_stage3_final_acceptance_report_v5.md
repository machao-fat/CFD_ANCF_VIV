# Stage 3 final acceptance report v5

## Decision

- `stage3_conditionally_passed=true`
- `stage3_fully_passed=false`
- `eligible_for_stage4_prototype=false`

## Blockers

- Ur=5.2 window-shift sensitivity is boundary-only, not robust (less than 2 of 3 pairs pass).
- At least one of the five SDOF points does not satisfy the common late-window steady criterion.
- The EB/ANCF comparison lacks two adjacent late windows with five effective structural periods each, or fails a physical criterion.

## Evidence

- Python discovery: 31/31 passed.
- MATLAB regression: 10/10 passed.
- Five SDOF points completed: `True`; safety pass: `True`.
- Ur=5.2 shifted-window audit: `boundary_window_pass_only`, 1/3 pairs.
- EB/ANCF long-time physical comparison: `long_time_online_comparison_completed_but_acceptance_incomplete`.
- EB/ANCF 60 s same-mesh model differences: `{'y_rms_relative': 0.0009414912581970637, 'peak_relative': 0.0004621932109142442, 'frequency_relative': 0.0, 'mean_power_relative': 0.0008958192640140584}`; independent CFD force RMS difference: `{'force_y_rms_relative': 4.9373489896223655e-05, 'eb_force_y_rms_N': 121.63786645256538, 'ancf_force_y_rms_N': 121.64387213853567}`.
- EB/ANCF measured late-window response frequency: `0.16739283399685215` Hz; each 27 s window contains `4.519606517915008` effective cycles, below the required five.
- Existing dt/dt/2 short-window screen retained from v4: `{'y_rms_relative_change': 0.004602829691632209, 'force_y_rms_relative_change': 0.005791020087291157, 'mean_power_relative_change': 0.011764451438884672, 'status': 'short_window_screening_pass_long_window_pending'}`; it is not relabeled as a long-window convergence proof.
- Engineering restart retained from v4: `{'strict_stepwise': False, 'native_file_adapter': True, 'engineering_restart': True, 'max_force_difference_N': 0.32040383, 'normalized_force_difference_percent': 0.064080766, 'post_first_two_samples_normalized': 4.9276e-07}`.
- Checkpoint splice continuity audits: `[('Ur4_v5_to130', 'pass', 130.0), ('Ur6p0_v5_to150', 'pass', 150.0), ('Ur7p1_v5_to142', 'pass', 142.0), ('Ur8p0_v5_to160', 'pass', 160.0), ('Ur5p2_extended', 'pass', 112.0)]`; these compare the last pre-checkpoint row with the first post-checkpoint row.
- 75 s EB/ANCF extension attempt: `{'ancf_online_long75': {'status': 'safe_stopped_before_target', 'reason': 'The 60 s completed audit already showed that the 27 s late windows contain only 4.52 structural cycles; the 75 s extension was stopped to avoid unbounded blind computation after confirming no safety failure.', 'last_time_s': 16.68, 'target_time_s': 75.0, 'raw_log_preserved': True, 'checkpoint_preserved': True, 'not_used_as_final_acceptance_evidence': True}, 'eb_online_long75': {'status': 'safe_stopped_before_target', 'reason': 'The 60 s completed audit already showed that the 27 s late windows contain only 4.52 structural cycles; the 75 s extension was stopped to avoid unbounded blind computation after confirming no safety failure.', 'last_time_s': 16.755, 'target_time_s': 75.0, 'raw_log_preserved': True, 'checkpoint_preserved': True, 'not_used_as_final_acceptance_evidence': True}}`; it was safely stopped and is not counted as final acceptance evidence.
- Figure source QA: `pass` for `3` Python generators.

The v3 0.36--0.38 Hz values were a doubled zero-crossing analysis error. They are obsolete as absolute frequencies; v5 reports DFT primary frequency and corrected zero-crossing diagnostics separately. Relative window-to-window changes are unaffected by the factor of two. No multi-slice or full-riser claim is made.

Weak coupling is not promoted to a strong-coupling requirement solely because the observed coupling work defect is about 1e-6 J while cycle fluid work is O(10^2) J. Aitken remains evidence-gated; it is required only if the completed physical audits show added-mass instability, residual growth, or time-step non-convergence.
