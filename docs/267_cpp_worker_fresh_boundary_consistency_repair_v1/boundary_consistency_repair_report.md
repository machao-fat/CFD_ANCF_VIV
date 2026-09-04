# Boundary consistency repair

Gate: `STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_CONSISTENCY_REPAIR_V1_GATE: pass`

The repair is offline only. It derives boundary phi/Uf from the same analytic velocity as the internal U/p/phi seed and writes explicit zero meshPhi. No physical core, parameter, threshold, or historical runtime was changed. A new explicit authorization is required before a fresh 40-step real run.
