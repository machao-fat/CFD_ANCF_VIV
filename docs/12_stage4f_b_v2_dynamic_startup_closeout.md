# Stage 4F-B-v2 Dynamic Startup Closeout

The v1 failure was a static-field-to-dynamic-mesh cold start.  This isolated
v2 run creates a real zero-motion dynamic state at `t=0.05 s` and carries the
complete dynamic field set into three fresh coupled cases.  The initial
dynamic force scale is finite and below the preflight limit.

The coupled three-step transaction is nevertheless blocked.  The ANCF state
starts without a static mean-drag equilibrium.  Mean streamwise drag therefore
produces streamwise acceleration; the third coupled step exceeds the frozen
`abs(Cd) <= 10` short-preflight guard.  This is not evidence of free VIV,
lock-in, a longer FSI response, or validation.

Only a separate v3 task that establishes structural equilibrium under the
mean load, or applies an explicit audited load ramp, may continue.  Restart,
five/nine-slice runs, long-time VIV, and experimental comparisons remain
unauthorized.

