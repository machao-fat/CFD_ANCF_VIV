from dataclasses import dataclass

@dataclass(frozen=True)
class StatisticalContract:
    minimum_cycles: int = 15
    minimum_samples: int = 300
    max_fft_zero_crossing_relative_difference: float = 0.05
    minimum_windows: int = 3

def evaluate(*, cycles: int, samples: int, windows: int, relative_difference: float,
             amplitude: float, amplitude_floor: float = 0.0) -> dict:
    if cycles < 15:
        return {"status": "not_evaluable_insufficient_cycles", "formal_frequency": False}
    if samples < 300 or windows < 3:
        return {"status": "not_evaluable_insufficient_samples_or_windows", "formal_frequency": False}
    if amplitude <= amplitude_floor:
        return {"status": "not_evaluable_low_amplitude", "formal_frequency": False}
    if relative_difference > 0.05:
        return {"status": "not_evaluable_frequency_disagreement", "formal_frequency": False}
    return {"status": "evaluable_by_frozen_contract", "formal_frequency": True}
