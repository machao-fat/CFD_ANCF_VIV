# Parameterized OpenFOAM multi-slice template

This directory is an independent stage-four template. It does not overwrite
the stage-three `single_slice_ancf_fsi` case. `generate_case.py` can copy that
case into a new per-slice case and render only the parameterized dictionaries.
The copied case retains the verified OpenFOAM 10 `interpolatingSolidBody`
motion solver and `ancfFileMotion` library.

Example (run in the OpenFOAM 10 environment or from PowerShell with a Python
interpreter):

```text
python generate_case.py --output <case-dir> \
  --reference-case <project>/cases/openfoam/single_slice_ancf_fsi \
  --case-id riser_demo_slice_0000 --slice-id 0 --s-ref-m 0.25 \
  --slice-length-m 0.25 --unit-span-m 1.0 --start-time 0 \
  --end-time 0.005 --delta-t 0.0025 \
  --exchange-dir coupling --motion-input coupling/motion.csv \
  --load-output postProcessing/cylinderForces
```

The output case owns its `coupling/`, `postProcessing/`, and log paths. The
current stage-three production motion library consumes the materialized
`motion.csv`/`motion_ready` view; the multi-slice adapter may generate that
bridge from immutable 0.2.1 payloads while retaining the original payload
hash and refusing old-step fallback. The generated metadata records
`0/motionScale` as a case-level static checkpoint file.

This is a short independent prescribed-motion/protocol smoke-test template,
not a double-slice CFD--ANCF free-VIV validation case.
