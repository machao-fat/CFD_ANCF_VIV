# High-Re URANS input audit

## Actual legacy input

The audited upstream v2.1 case is kOmegaSST, not kOmegaSSTLM. It is a read-only parameter reference. The Luna case creates fresh ReThetat and gammaInt fields and does not copy legacy force history or statistics.

Frozen input: U=0.43414375179615955 m/s; D=0.02841 m; nu=1e-6 m2/s; rho=1000 kg/m3; Re=12334.023988528894; b_mesh=0.02841 m; Aref=0.0008071281 m2; fixed dt=0.0001 s.

## Transition model audit

OpenFOAM 10 source was read from /opt/openfoam10. ReThetat and gammaInt are MUST_READ fields. The ReThetat0 zero-pressure-gradient correlation was independently reimplemented and tested. Tu is used in percent by the source. Scenario N uses Tu=1.0 percent, I=0.01, Lt/D=0.07, ReThetat=584.3016, and gammaInt=1. Scenario S is the audited upper-input sensitivity and was not run because scenario N failed the entry gate.

The transition fields are model initialization/engineering assumptions, not measured experiment values. No post-processing clipping or parameter fitting was used.
