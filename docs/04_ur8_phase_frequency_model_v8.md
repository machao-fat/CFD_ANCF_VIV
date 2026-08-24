# Ur=8 phase/frequency model v8

## Data split

The 111.2525--240.0 s record is split chronologically into 40% training, 30% validation and 30% independent testing. The previously omitted 200.0025--221.25 s interrupted segment is included; overlapping restart rows are de-duplicated by time and step.

The DFT diagnostics are separate from zero-crossing diagnostics. No test-segment samples are used during model selection.

## Candidate models

| model | validation residual | independent test residual | BIC |
|---|---:|---:|---:|
| M0 fixed force frequency | 17.5006% | 28.4896% | -544012.489 |
| M1 joint fs/lambda | 1.2594% | 1.3052% | -827230.425 |
| M2 measured Fy(t)+homogeneous | 0.0665% | 0.0814% | -1135064.811 |

Selected model: **M2_measured_force_driven_plus_homogeneous**. M2 uses m=7853.98 kg, c=123.37 N s/m and k=4844.73 N/m without fitting or changing them.

The joint-frequency M1 search was limited to 0.139273--0.179636 Hz, derived from the train-segment displacement/force peaks and its frequency resolution 0.019418 Hz.
