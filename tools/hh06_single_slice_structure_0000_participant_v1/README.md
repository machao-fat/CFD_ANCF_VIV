# HH06 `Structure_0000` single-slice wrapper

This is an adapter, not a new ANCF solver.  It loads the verified HH06 P1
`REF_NE32` static state, consumes one mapped resultant `Force` point, delegates
the global load assembly and worker request to the existing generic
coordinator/persistent-worker stack, and writes one absolute section
`Displacement` point.  It uses `parallel-implicit` preCICE semantics with
checkpoint/rollback around every tentative window.

## Offline validation

```text
python structure_0000_participant.py --case <slice0000> --audit-only
```

The command never imports/initializes preCICE and never starts a worker.  It
fails closed if the checked-out Python wire protocol cannot represent the P1
SHM1 hydrodynamic-region extension.

## Explicit live invocation

Only after a separate authorization and a successful audit:

```text
python structure_0000_participant.py --case <slice0000> --run --worker <worker>
```

The wrapper does not accept CFD face forces as ANCF nodal forces.  preCICE
maps the 200-fluid-face interface to one structural coupling point; the
participant then applies the existing `ForceSample` strip-resultant rule once
and the coordinator assembles the generalized ANCF load internally.
