# HH06 Fluid rollback runtime fingerprint audit

## Scope and execution boundary

This audit used an **isolated copy** of the HH06 case. The original case
`/home/machao/OpenFOAM/coupling/singal_slice/slice0000` was not modified.
No 50-window run, production FSI run, solver-parameter change, turbulence
change, mesh change, worker change, or SHM1 change was performed.

The diagnostic run used exactly one parallel-implicit coupling window:

- restart field: global time `30 s`;
- OpenFOAM `deltaT`: `0.0002 s`;
- diagnostic coupling window: `30.0000 -> 30.0002 s`;
- preCICE iterations: two trials, one rollback and one final commit;
- fluid participant: `Fluid_0000`;
- temporary structure participant: `Structure_0000`.

The structure participant deliberately used two deterministic trial
displacements (`0.0001 m` and `0.0002 m`) to exercise the implicit retry path.
These are diagnostic inputs only and are not HH06 physical results.

## Source and binary identity

The deployed production adapter was not replaced:

| item | value |
|---|---|
| production adapter | `/home/machao/OpenFOAM/machao-10/platforms/linux64GccDPInt32Opt/lib/libpreciceAdapterFunctionObject.so` |
| production SHA256 | `26ad8529822f96ca8ddfb3370f85257b0d19b56958538d6073cf8af897aac572` |
| temporary diagnostic library | `/home/machao/OpenFOAM/hh06_fluid_rollback_runtime_fingerprint_audit_v1/diagnostic_lib/libpreciceAdapterFunctionObject.so` |
| diagnostic SHA256 | `85cd9a6a0a1bf4999662f376f825844d235dcebcdf94f5cb57414443cbc67306` |
| diagnostic `Adapter.C` SHA256 | `E865830DB4CA0182BE32FDD24B6BB29AD20C308D7583421518E2C503729625C1` |
| diagnostic `Adapter.H` SHA256 | `9BE0190B6654D4F9D5FC371250C50BCE6578EE55FFF4A9A50BDA508E122AD06F` |

The diagnostic source is an instrumented copy of
`tools/reproducible_openfoam10_adapter_rollback_qualification_v1/.time-layer-work-diagnostic-base`.
The separate `verified_build006_source` contains an OF10-owned
`meshHistoryCheckpoint` dependency that is not present in the active
`/opt/openfoam10` installation; it therefore was not substituted silently.
Consequently, this report is diagnostic evidence from the temporary build,
not a claim that the production binary has the same instrumentation or exact
source provenance.

## Event order

The recorded order was:

1. `CHECKPOINT_WRITE`, window 1, iteration 0, `t=30.0 s`;
2. first fluid trial at `t=30.0002 s`;
3. `PRE_ROLLBACK_TRIAL`, window 1, iteration 1;
4. adapter checkpoint restore, followed by `POST_ROLLBACK_BEFORE_NEXT_INPUT`,
   restored time `30.0 s`;
5. second structure input and second fluid trial at `t=30.0002 s`;
6. `FINAL_COMMIT`, window 1, iteration 1.

The structure-side evidence records one checkpoint read/rollback and two
accepted trial results. The full raw evidence is in
`adapter_rollback_trace.jsonl` and `participant_evidence.json` beside this
report.

## Fingerprint comparison

The following hashes are FNV-1a fingerprints of the canonical OpenFOAM field
serialization emitted by the temporary adapter.

| state | checkpoint | after rollback | equal? |
|---|---|---|---|
| `points` | `84b09858d2e5c718` | `84b09858d2e5c718` | YES |
| `oldPoints` | `84b09858d2e5c718` | `84b09858d2e5c718` | YES |
| `U` | `61e10298d5371efa` | `61e10298d5371efa` | YES |
| `p` | `ab1feb7ccf1379cf` | `ab1feb7ccf1379cf` | YES |
| `phi` | `5e737856cbb4000a` | `5e737856cbb4000a` | YES |
| `k` | `a1bd220b765c52dd` | `a1bd220b765c52dd` | YES |
| `omega` | `6b21c90b8ea937f2` | `6b21c90b8ea937f2` | YES |
| `nut` | `32af9d4eac163202` | `32af9d4eac163202` | YES |
| `pointDisplacement` | `403a37f08d8872c4` | `403a37f08d8872c4` | YES |
| `cellDisplacement` | `054f811aba347c5a` | `054f811aba347c5a` | YES |
| `meshPhi` | not observable at checkpoint | `643e6457c48e9183` | NOT COMPARABLE |

`meshPhi` was visible after the trial but was not registered/observable at the
checkpoint event in this diagnostic build. It is therefore not valid to claim
complete mesh-flux rollback from this run.

## Health observations

- Both fluid and structure return codes were zero.
- Two fluid solves completed at `30.0002 s` without FPE, NaN/Inf signature,
  OpenFOAM fatal error, negative-volume message, or preCICE fatal error.
- Courant number: mean `0.01601199855`, maximum `0.4182184878` for both trial
  solves.
- Maximum reported absolute local continuity error:
  `8.145416056e-09`.
- Maximum absolute global continuity error:
  `1.80747064e-10`.
- At the checkpoint, `k` ranged from `2.7019925327e-10` to
  `1.5897010426e-02`; `omega` ranged from `1.9835945737` to
  `9.3792847492e04`; `nut` ranged from `2.8808087284e-15` to
  `2.803142214e-04`.
- After rollback those ranges and the field hashes returned to the checkpoint
  values. No post-rollback omega explosion occurred in this one-window run.
- The point-delta mesh-velocity proxy was `0 m/s` because the diagnostic
  source did not observe a changed mesh-point state in this run. This does not
  prove a moving-mesh velocity path was exercised.

## Structure displacement consistency

The temporary structure participant intentionally supplied:

- trial 1: `[0, 0.0001] m`;
- retry trial 2: `[0, 0.0002] m`.

The values differ as expected for a deterministic implicit retry stimulus; this
is not a checkpoint corruption signal. It also means this run does not prove
that two physically converged structure inputs are identical. It proves only
that the fluid state was restored before the second trial was solved.

## Answers to the requested checks

**A.** `points`, `U`, `p`, `phi`, `k`, `omega`, `nut`,
`pointDisplacement`, and `cellDisplacement` matched their checkpoint hashes.
`meshPhi` was not comparable because no checkpoint fingerprint existed.

**B.** A nonzero mesh-velocity recomputation was not exercised; the observed
point-delta proxy was zero. The diagnostic cannot certify the moving-mesh
velocity path.

**C.** `omega` was finite before and after rollback and its post-rollback hash
and range exactly matched the checkpoint. No rollback-induced omega anomaly was
observed in this window.

**D.** The structure inputs were intentionally different between trials. The
physical window identity (`30.0 -> 30.0002 s`, `dt=0.0002 s`) was the same, but
the diagnostic displacement stimulus was not; this is expected for the retry
test and is recorded explicitly.

## Classification

`DO_NOT_PASS_PRODUCTION_FLUID_ROLLBACK_AUDIT`

Reason: the temporary run demonstrates restoration of the listed registered
fields and stable one-window numerics, but does not provide an authoritative
production-binary identity, a checkpoint-time `meshPhi` fingerprint, or a
nonzero mesh-motion/velocity exercise. It must not be used to clear the HH06
production FSI blocker.

No production FSI was started and the original case has no new time directory.

