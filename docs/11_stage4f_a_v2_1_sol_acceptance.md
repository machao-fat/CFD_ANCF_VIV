# Stage 4F-A-v2.1 Sol Acceptance

## Decision

**Passed with scope limits.** The static negative-tension result for `m*=10, beta=0.05` is a rejection of that candidate, rather than a failure of every candidate. The independently verified `m*=5, beta=0.01` structure is selected for the low-Re method benchmark.

## Evidence

- Selected static state: `T/EA=0.004525`, minimum tension `6.3815e5 N`.
- EB/ANCF wet-mode and 16/32-element consistency are inherited from read-only v2 evidence.
- New 0.2.1 three-, five-, and nine-slice identities were materialized with the production H/H-transpose mapping functions.
- The largest virtual-work error is `5.33e-15`, below the `1e-12` criterion.
- The v2 evidence hash audit passed. The new closeout tests passed 3/3 and `compileall` passed.

## Next Gate

Only a short, real **three-slice low-Re CFD-ANCF preflight** is authorized next. It must use the selected structure, one uniform flow `U=1 m/s`, `Re=100`, `R_GL=I`, a 3-slice 50 m manifest, the existing 0.2.1 checkpoint protocol, and an explicit stop rule. Five/nine slices, long-time VIV statistics, lock-in, and experimental claims remain out of scope.
