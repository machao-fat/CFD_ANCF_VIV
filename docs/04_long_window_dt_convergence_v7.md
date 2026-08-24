# v7 dt/dt/2 convergence evidence

The existing same-parameter runs use dt=0.0025 s and dt/2=0.00125 s over the common 5--10 s interval. The screening changes are y RMS 0.460%, half amplitude 0.503%, Fy RMS 0.579%, Cl RMS 0.579%, primary DFT frequency 0.000%, and mean power 1.176%. These are below the screening limits.

This is **not** the requested long-window scheme-A evidence: both runs start at 0 s, end at 10 s, and the common window contains only 0.9615 natural-frequency cycles. The formal v7 long-window gate therefore remains false. A valid closure requires the same late CFD/structure state, identical physical response-cycle boundaries, and at least 3 (preferably 5) full response cycles at both time steps. This report deliberately does not relabel the short-window screen as long-window convergence.
