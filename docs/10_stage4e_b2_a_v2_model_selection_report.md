# Stage 4E-B2-A-v2: model-selection status

Frozen physical input was `D=0.02841 m`, `rho=1000 kg/m^3`, `nu=1e-6 m^2/s`, and the high representative speed was read from the frozen Route-G profile as `|U|=0.43414375179615955 m/s`, `Re=12334.023988528894`.

The laminar and kOmegaSST candidates both passed the six short runtime prechecks. Those windows were only `0.005 s`, with zero evaluable vortex cycles, so they cannot select a model or support a frequency claim. The formal sequence reached one high-laminar-medium case only. Although that solver log ended normally, the full CFL history violated the hard stop (`1.70648 >= 0.8`). The sequence was stopped before formal SST screening.

Therefore `model_screening_v2.json` records `not_evaluable_incomplete_formal_window`; no laminar/SST choice is frozen. The deterministic anti-symmetric perturbation contract remains in force (`epsilon=0.0025` and `0.005` are candidates, equal-volume upper/lower regions and zero net transverse momentum), but perturbation sensitivity was not run after the hard stop.
