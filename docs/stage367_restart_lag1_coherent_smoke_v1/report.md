# Stage 367 lag-1 coherent restart Smoke

This is one fresh, explicitly authorized 40-step Smoke from the Stage366
offline candidate. The OpenFOAM field clock is 80.0 s and the structure
bootstrap state is the lag-1 state at 79.995 s. It uses new stage, run, case,
runtime, and results identities and never continues automatically.

The launcher requires the first-step quality audit and stops fail-closed on
any nonzero return, missing quality record, time/identity mismatch, or mesh
quality failure. No MATLAB is used; the C++ worker and three OpenFOAM slices
run under the shared preCICE launcher. A passing Smoke does not authorize a
long run.
