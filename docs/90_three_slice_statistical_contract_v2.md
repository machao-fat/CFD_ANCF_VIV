# Three-Slice Statistical Contract V2

This contract is a versioned replacement for the *statistical interpretation*
of future three-slice runs.  It does not alter the formal 0.2.1 protocol or
any completed Gate.

Primary physical statistics are each slice's de-meaned transverse-force RMS
and peak-to-peak range, a declared transverse structural displacement, their
dominant frequencies, and pairwise phase relations.  The arithmetic average
of the three forces is retained only to diagnose phase cancellation.  A
physical total is reported only when each slice declares its tributary length
or area and its force-unit convention.

Numerical-quality and transfer-conservation checks remain separate: finite
values, CFL/continuity records, restart/identity continuity, virtual work,
force balance, and moment balance.  Stable response statistics cannot waive a
quality or conservation failure.

The V2 project thresholds must be declared before a future run, not selected
after examining its result.  The Stage 384 use of them is explicitly a
retrospective diagnostic of legacy evidence and cannot promote that evidence.
They are engineering acceptance thresholds, not universal VIV constants. Their
methodological basis is: Sarpkaya (2004), Williamson and Govardhan (2004), and
Farhat, Lesoinne and Le Tallec (1998).
