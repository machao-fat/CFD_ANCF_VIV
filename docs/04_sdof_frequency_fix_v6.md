# v6 SDOF frequency correction

The old zero-crossing implementation used `2 / mean(crossing[i+2]-crossing[i])`. Because alternating positive and negative crossings make the two-step difference a complete period, that expression doubled the physical frequency. The corrected implementation is `1 / mean(crossing[i+2]-crossing[i])`.

DFT/FFT-equivalent frequency and zero-crossing diagnostic frequency are stored separately. The v3 0.36--0.38 Hz Ur=5.2 values are obsolete; the corrected late response is about 0.181--0.189 Hz and Ur=5.2 is near synchronization (`f/fn` about 0.984 in the final response-cycle window). Automated tests cover a 0.2 Hz sine, offset, linear drift, deterministic noise and an explicit no-0.4 Hz assertion.
