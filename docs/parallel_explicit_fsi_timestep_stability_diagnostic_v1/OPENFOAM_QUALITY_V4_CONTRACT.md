# OPENFOAM Quality V4 Contract

V4 applies only to future runs. V3 evidence and its failures remain immutable.

`Ux`, `Uy`, and `p` retain their terminal-residual, finite-value, continuity, and Courant hard gates. `pcorr` remains a flux-correction validity solve. `cellDisplacementx/y` must be present, finite, complete, and meet the actual `fvSolution` tolerance; their iteration count above 200 is recorded as an auxiliary efficiency/conditioning warning, not a numerical-invalid verdict. The audited `fvSolution` supplies `tolerance=1e-8` and `relTol=0` for this path, but no separately frozen `maxIter=200` validity limit. Unknown solve fields fail closed.
