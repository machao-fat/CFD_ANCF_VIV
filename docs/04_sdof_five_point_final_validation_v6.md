# Five-point SDOF v6 validation

The campaign reuses existing checkpoints and extends only the permitted points. The measured-response-cycle windows are the final windows.

| Ur | final time (s) | passing pairs | final steady | classification | response f (Hz) | f/fn | max CFL |
|---:|---:|---:|:---:|:---|---:|---:|---:|
| 4.0 | 140.000 | 0/3 | False | transitional_or_unsteady | 0.175476 | 0.6958 | 0.1487 |
| 5.2 | 130.000 | 3/3 | True | locked_or_near_lockin | 0.189209 | 0.9839 | 0.1805 |
| 6.0 | 190.000 | 2/3 | True | locked_or_near_lockin | 0.170135 | 0.9888 | 0.1755 |
| 7.1 | 142.000 | 3/3 | True | locked_or_near_lockin | 0.145721 | 1.0184 | 0.1755 |
| 8.0 | 200.000 | 0/3 | False | transitional_or_unsteady | 0.159454 | 1.2451 | 0.1755 |

Ur=5.2 has 3/3 passing late window pairs and therefore satisfies the v6 robustness requirement. Ur4 and Ur8 remain outside the formal five-point steady gate in the measured-cycle analysis; their raw data, checkpoints, mesh audits and safety logs are retained. The five-point formal gate is therefore not passed.

The v5 0.36--0.38 Hz response values were the known doubled zero-crossing frequency error and are not reused as absolute frequencies. v6 keeps DFT and corrected zero-crossing fields separate.
