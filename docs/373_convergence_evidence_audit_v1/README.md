# Stage 373 Convergence Evidence Audit

This is a read-only audit of the completed Stage 372 runtime. It does not
modify Stage 372 fields, logs, configuration, or result Gate, and starts no
MATLAB, WSL, OpenFOAM, or CFD process.

The audit verifies the 23,960-record identity chain and recalculates the
mean-force frequency using a declared robust rule: 0.05 s samples, 1.0 s
moving average, positive peaks only, and a 4.0 s minimum peak separation.

The original accumulator's unconstrained 2.0 s local-maximum rule accepted
negative local maxima. That explains its spurious short periods and failed
frequency-drift / FFT-versus-peak checks. Robust reanalysis gives approximately
0.160--0.162 Hz in every 40 s window, with 0.80% frequency drift.

This does not establish formal convergence. The protected cross-slice mean
force has 32.8% peak-to-peak amplitude drift across the same three windows.
Although individual slice forces and interface positions are substantially
more stable, cross-slice phase cancellation cannot be reinterpreted as a
formal stable-structure claim. The Gate remains `not_evaluable` and the
formal statuses remain `not_completed`.

Run the audit again, read-only:

```powershell
python .\tools\stage373_convergence_evidence_audit_v1\audit_stage372.py
```

Run its unit tests:

```powershell
python -m unittest discover -s .\tests\stage373_convergence_evidence_audit_v1 -p "test_*.py" -v
```
