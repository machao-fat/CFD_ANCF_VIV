def timeline_ok(windows):
    for a,b in zip(windows,windows[1:]):
        if a['end_tick'] != b['start_tick']: return False
    return True
def evaluate(cycles,samples,stable,rel_diff,amp,floor=0):
    if cycles<15:return 'not_evaluable_insufficient_cycles'
    if samples<300 or stable<3:return 'not_evaluable_insufficient_samples_or_windows'
    if amp<=floor:return 'not_evaluable_low_amplitude'
    if rel_diff>.05:return 'not_evaluable_frequency_disagreement'
    return 'evaluable_by_frozen_contract'
