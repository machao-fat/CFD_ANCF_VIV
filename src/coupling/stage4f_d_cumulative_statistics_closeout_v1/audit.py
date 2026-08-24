CONTRACT={"minimum_cycles":15,"minimum_samples":300,"stable_windows":3,"max_fft_zero_crossing_difference":.05}
def validate_windows(windows):
    times=[]
    for w in windows:
        if w.get('excluded'): continue
        if times and w['start_tick']!=times[-1]: return False
        times.append(w['end_tick'])
    return True
def status(cycles,samples,stable,rel_diff,amplitude,floor=0):
    if cycles<15:return 'not_evaluable_insufficient_cycles'
    if samples<300 or stable<3:return 'not_evaluable_insufficient_samples_or_windows'
    if amplitude<=floor:return 'not_evaluable_low_amplitude'
    if rel_diff>.05:return 'not_evaluable_frequency_disagreement'
    return 'evaluable_by_frozen_contract'
