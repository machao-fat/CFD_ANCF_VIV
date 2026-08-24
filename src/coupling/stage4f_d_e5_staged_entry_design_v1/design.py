def candidate(added_s, wall_per_s=1986.4, disk_per_s=11110000000):
    steps=round(added_s/.00125)
    return {'steps':steps,'blocks':steps//10,'wall_s':wall_per_s*added_s,'disk_bytes':round(disk_per_s*added_s)}
def status(cycles,samples,windows,diff,amp,floor=0):
    if cycles<15:return 'not_evaluable_insufficient_cycles'
    if samples<300 or windows<3:return 'not_evaluable_insufficient_samples_or_windows'
    if amp<=floor:return 'not_evaluable_low_amplitude'
    if diff>.05:return 'not_evaluable_frequency_disagreement'
    return 'evaluable_by_frozen_contract'
