# Stage 4F-B-v5 Gate

Status: passed for the bounded low-Re three-slice CFD-ANCF explicit-weak preflight.

The reconciled ANCF equilibrium and terminal CFD geometry were matched at the
three slice reference points before coupling. Three real global steps completed
at 1.5025, 1.5050, and 1.5075 s. The largest CFL was 0.1371123039; the largest
absolute drag coefficient was 1.0371975450. Raw OpenFOAM forces, unit-span
forces, one-time slice integration, and forceCoeffs agree to the recorded
tolerance. The largest H/H^T virtual-work relative error was
2.2683231077e-16.

The three committed checkpoints validate their protocol identity and copied CFD
state files. A restart from checkpoint 0 completed steps 1 and 2; the ANCF
state relative error against uninterrupted execution was zero.

The final repository unittest summary is 645 tests, OK. The outer log pipeline
timed out after unittest had printed its summary because a task-owned fake-tree
test process remained alive; it was identified by its unique token and cleaned
by exact PID. This does not change the unittest result.

This Gate does not authorize five/nine-slice work, long-time VIV, lock-in,
experimental validation, or any Stage 4E physical-validation claim.
