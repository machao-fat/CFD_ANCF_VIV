# preCICE Time-Layer Contract V1

This contract applies to the source-pinned OpenFOAM Foundation 10 adapter
baseline `d53753b1c927b2413b02299c9da15725b3e772f0`, preCICE 3.4.1, one
OpenFOAM physical step per coupling window, and `dt = 0.005 s`.  Fluid
subcycling is forbidden.  PIMPLE outer iterations and implicit fixed-point
iterations are numerical iterations, not physical time steps.

| Event | OpenFOAM physical time | Coupling-relative time | Data read/write | `relativeReadTime` |
| --- | ---: | ---: | --- | ---: |
| Precursor restart / window start | 0.100 s | 0 | initial total Displacement is available to Fluid | 0 |
| Structure trial write | 0.100 s checkpoint state | 0 | Structure writes its trial total Displacement | n/a |
| Fluid tentative solve | 0.100 -> 0.105 s | 0 -> 0.005 s | Fluid applies that trial Displacement, solves, and writes Force | n/a |
| `advance(dt)` returns with rollback requested | solver state is restored to 0.100 s | still window 1 | Fluid consumes the next trial Displacement sample at the just-completed window end | `dt` |
| Final converged iteration | 0.105 s | 0.005 s | one physical commit; final Force belongs to the converged geometry | n/a |

`Participant::readData(..., 0)` samples the beginning of the participant's
current time step. `readData(..., dt)` samples its end. Therefore the adapter
uses `0.0` only after `initialize()` for initial data, and uses
`precice_->getMaxTimeStepSize()` after `advance()` before the next rollback
trial. It must not use a hard-coded `0.0` at the latter site.

The Python structure backend writes Displacement, calls `advance(dt)`, then
reads Force with `relativeReadTime=0`. In that participant's normal
post-advance path, its current step starts at the just-reached target time, so
the read is the Force at that target time. It is not the same adapter rollback
location and is not changed by this contract.

Each implicit iteration has a separate attempt identity, but no separate
physical time. Intermediate trial fields and forces are numerical-iteration
evidence only; only the converged iteration is committed physical evidence.
