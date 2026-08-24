# Stage 4F-C-v1 Repair1 Classifier Audit

The repair implementation is isolated under `src/coupling/stage4f_three_slice_short_window_v1_repair1` and does not modify the v1 classifier or retained results.

The old classifier matched `Floating point exception` anywhere in a log. The repair accepts the normal OpenFOAM startup banner `sigFpe: Enabling floating point exception trapping (FOAM_SIGFPE)` and rejects only explicit `FOAM FATAL ERROR`/`FOAM FATAL IO ERROR`, bounded `NaN`/`+Inf`/`-Inf` tokens, negative volume, an actual floating-point crash line, or a non-zero solver return code. `End` and strict CFL are still required.

Offline repair tests collected 37 tests with 0 failures and 0 errors. All three retained attempt2 logs reclassify as passed with return code 0; their maximum CFL is `0.1363182835702355` and their SHA-256 values are recorded in `results/stage4f_three_slice_short_window_v1_repair1/classifier_reaudit_old_attempt2.json`.

This classifier result does not convert the old run into a successful CFD run. The old run remains immutable evidence, and the new real attempt was blocked before its first ANCF prediction by the independent MATLAB ApplicationService 5001 failure.
