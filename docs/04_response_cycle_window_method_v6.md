# v6 response-cycle-aligned window method

The late displacement is linearly detrended. The primary frequency is a zero-padded direct DFT (`numpy.fft.rfft`); positive-going zero crossings with linear interpolation are used only to construct boundaries and as a diagnostic. The last 11 reliable crossings define two adjacent five-response-cycle windows. A window is not accepted by selecting a visually quiet short segment: it must contain exactly five measured cycles, and the last three cycles are audited for energy balance.

The reliability gate is period coefficient of variation below 5% and DFT/zero-crossing frequency difference below 5%. The response-cycle criterion compares displacement RMS, half-amplitude, peak, force RMS, lift RMS, mean power and primary frequency. The limits are 5% for amplitudes/forces/power and 2% for frequency. Low-power points may use an absolute mean-power floor of 0.5 W, but they still require displacement/force stationarity, no persistent mechanical growth and a reliable frequency.

The natural-period windows remain reported for comparison only; they are not the v6 final acceptance windows.
