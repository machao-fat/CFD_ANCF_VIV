# Lock-in and synchronization classification v5

Tier 1: `frequency_synchronized` means 0.95 <= f_response/f_n <= 1.05 and the DFT/zero-crossing diagnostic is reliable. Otherwise the state is `outside_frequency_sync`; if the frequency estimate is unreliable it is `frequency_unresolved`.

Tier 2: `locked_or_near_lockin` is allowed only after the late-window stationarity gate, with positive non-noise fluid input and a compatible force--velocity phase. Frequency synchronization alone is never called lock-in. Failed or incomplete late-window stationarity is classified as `transitional_or_unsteady`.
