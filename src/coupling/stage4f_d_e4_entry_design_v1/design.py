CONTRACT = {"minimum_cycles": 15, "minimum_samples": 300, "windows": 3, "max_frequency_difference": 0.05}

def projection(added_seconds, step=0.00125, measured_wall=3841.187, measured_disk=2221893708):
    steps = round(added_seconds / step)
    return {"steps": steps, "blocks": steps // 10, "wall_clock_s": measured_wall * added_seconds / 0.2,
            "disk_bytes": round(measured_disk * added_seconds / 0.2), "within_4h": measured_wall * added_seconds / 0.2 <= 14400,
            "within_20GB": measured_disk * added_seconds / 0.2 <= 20 * 1024**3}

def statistical_status(cycles, samples, windows, freq_difference, amplitude, floor=0.0):
    if cycles < CONTRACT["minimum_cycles"]: return "not_evaluable_insufficient_cycles"
    if samples < CONTRACT["minimum_samples"] or windows < CONTRACT["windows"]: return "not_evaluable_insufficient_samples_or_windows"
    if amplitude <= floor: return "not_evaluable_low_amplitude"
    if freq_difference > CONTRACT["max_frequency_difference"]: return "not_evaluable_frequency_disagreement"
    return "evaluable_by_frozen_contract"
