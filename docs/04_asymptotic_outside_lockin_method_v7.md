# v7 forced/free asymptotic decomposition

The late response is fitted as

`y(t)=c0+c1*t+As*sin(2*pi*fs*t+phis)+An*exp(-lambda*(t-t0))*sin(2*pi*fn*t+phin)`.

`fs` is measured independently from late pressure/viscous total force and `Cl` with a detrended, zero-padded DFT. `fn` is calculated from the unchanged structural parameters. For each trial `lambda`, all other coefficients are solved by `numpy.linalg.lstsq`; `lambda` is bounded and minimized with `scipy.optimize.minimize_scalar(method='bounded')`. The executed environment records SciPy 1.13.1 and NumPy 2.0.2. No Ur-number branch is present in the classifier.

The diagnostic separates the raw response, forced component, free component, full fit, first-half extrapolation and residual spectrum. A fitted component is never relabelled as an FFT/DFT frequency. Ur=4 is allowed to use the protocol's negligible-free-tail exception: when the fitted free/forced ratio at the end of the accepted tail is below 5%, its decay rate is treated as weakly identifiable, while the independent force/frequency, fit, prediction, energy and safety gates remain mandatory.

The twelve-condition summary and all numerical values are stored in `results/04_sdof_corrected_campaign/asymptotic_v7/Ur4_asymptotic_v7.json` and `Ur8_asymptotic_v7.json`.
