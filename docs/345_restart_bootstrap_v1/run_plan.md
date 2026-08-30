# Stage345 restart bootstrap preparation

This offline preparation creates a candidate state with an explicit two-step
lag relative to the saved Stage341 `80 s` OpenFOAM field. It is intended to
avoid the direct `final_q` displacement jump observed in the failed Stage343
continuation.

The candidate is not a completed restart and does not authorize a CFD run. A
fresh short smoke must verify the bootstrap acknowledgement and the first two
coupling windows before any longer continuation is considered.
