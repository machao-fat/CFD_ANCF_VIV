# Ur=5.2 common-checkpoint dt/dt2 convergence v8

Both branches start from the same synchronized physical state at **130.0 s** and the same OpenFOAM `130` field directory. The coarse branch uses dt=0.0025 s; the refined branch uses dt=0.00125 s and the corresponding CFD coupling interval.

Each branch is analyzed using 3 complete positive-going displacement zero-crossing cycles (minimum formal evidence is three). The coarse window is 134.270709--149.903973 s; the refined window is 134.270773--149.903124 s. Common overlap: 134.270773--149.903124 s.

| metric | relative change |
|---|---:|
| y RMS | 0.179% |
| half amplitude | 0.121% |
| Fy RMS | 0.626% |
| Cl RMS | 0.626% |
| Cd mean | 0.131% |
| displacement frequency | 0.000% |
| lift frequency | 0.000% |
| mean power | 1.382% |

Formal result: **formal_long_window_convergence_pass**. Energy residuals, CFL, finite values, mesh safety and |y|<1.5D are included in the JSON criteria. Any CFD time directories beyond the committed checkpoint are retained and are not used in the formal window.
