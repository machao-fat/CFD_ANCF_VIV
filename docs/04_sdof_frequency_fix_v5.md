# Ur=5.2 frequency-method correction v5

`zero_crossing_frequency()` now returns `1 / mean(crossings[i+2] - crossings[i])`. The interval already spans one complete period; the previous factor of two was a frequency-doubling bug. A project search found no second independent implementation of that formula. DFT and corrected zero-crossing values are now stored in separate, explicitly labelled fields.

The v3 report values around 0.36--0.38 Hz are obsolete absolute frequencies caused by the doubled analysis. Window-to-window relative changes are essentially unchanged by a common factor of two. DFT is primary for response and lift; zero crossing is diagnostic only.

| Window | Response DFT (Hz) | Response zero-crossing diagnostic (Hz) | Lift DFT (Hz) | fn (Hz) | Response DFT/fn |
|---|---:|---:|---:|---:|---:|
| 60--86 s | 0.1879833 | 0.1890041 | 0.1879833 | 0.1923077 | 0.9775 |
| 86--112 s | 0.1899500 | 0.1891095 | 0.1879833 | 0.1923077 | 0.9877 |

The response is therefore near the natural frequency, but the separate stationarity and window-shift gates remain necessary. The three shifted-window pairs pass only 1/3, so Ur=5.2 is not called robustly steady in v5.

Frequency tests cover a 0.2 Hz sine, constant offset, linear drift, deterministic noise, and a fundamental plus second harmonic; all passed in the 31-test discovery run.
