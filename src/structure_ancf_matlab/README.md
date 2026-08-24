# Vertical TTR ANCF structural solver (MVP)

This directory is a clean structural refactor for the thesis project. It does not modify or import the legacy `Run4v4_wu` package.

## Public entry points

```matlab
model = vertical_ttr_case('nElem', 10, 'nSlices', 11);
state = ancf_initialize(model);
motion = ancf_slice_motion(state);
state = ancf_advance_step(state, slice_force_N, dt);
motion = ancf_slice_motion(state);
ancf_write_slice_motion_csv(motion, 'coupling/slice_motion.csv');
[slice_force_N, meta] = ancf_read_slice_loads_csv('coupling/slice_loads.csv', state.model);
ancf_save_checkpoint(state, 'coupling/state_step_00000001.mat');
state = ancf_load_checkpoint('coupling/state_step_00000001.mat');
```

`slice_force_N` is an `nSlices x 3` array in global `[Fx,Fy,Fz]` order. The default representation is an integrated force per slice in newtons. The generalized load is assembled as `H3' * Fslice`.

The internal force and tangent are now evaluated analytically from the Green-strain and curvature energy. This keeps the new package independent of generated Symbolic Math Toolbox files while avoiding the very high cost of the first finite-difference MVP.

The top guide fixes x/y position and the top axial force is applied in +z. The bottom position is fixed. Coordinates are SI and use +z from bottom to top.

The CSV helpers use atomic temporary-file replacement for motion requests. Load files are validated against the case slice positions and must contain integrated `[Fx,Fy,Fz]` in newtons.

Run the regression test from MATLAB:

```matlab
results = test_vertical_ttr_solver;
```
