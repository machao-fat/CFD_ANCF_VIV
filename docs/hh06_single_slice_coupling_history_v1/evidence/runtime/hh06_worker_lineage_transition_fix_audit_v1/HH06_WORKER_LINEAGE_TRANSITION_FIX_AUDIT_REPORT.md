# HH06_WORKER_LINEAGE_TRANSITION_FIX_AUDIT

## Final gate

PASS_HH06_WORKER_LINEAGE_TRANSITION_FIX_AUDIT

The isolated worker accepted all ten production-protocol requests and returned
all ten response headers. The sequence-6 transition that failed in the
previous 5-window run now succeeds. No OpenFOAM, preCICE, Fluid_0000, or
production FSI process was started.

## Scope and source identity

The first attempted isolated build used the current working-tree worker source
(ancf_worker_main.cpp SHA256
53BF8FDD8F4D5CA3DDC6FFCFFA876E5178A12453A5B776650B5A4D8F78A93181).
That source was not the previously qualified wire baseline and failed earlier
at sequence 1 with an independent wire-layout error; this evidence is retained
in lineage_transition_test_result_original_worker.json and is not counted as
the lineage qualification.

The qualification build uses the previously identified qualified source blob:

D:/研二文件/开题准备/CFD_ANCF_VIV_BUILD/hh06_shm1_source_blob_355640e1

| source/build item | SHA256 |
|---|---|
| qualified baseline ancf_worker_main.cpp | 83F2D643F855894C8E74AAA11D0C76684E74886FFA0CCFA044B9FB368367DEB9 |
| patched isolated ancf_worker_main.cpp | 22072322A4D0559C1958C81C0D70D57AB89C0C4D5B30DB54FA86E0863D044E0C |
| ancf_kernel.cpp | 6DDE195A8EA27F253A21D4A859BF41A620697963AB0A834BB9D982B51863AC06 |
| ancf_kernel.hpp | C1182AB921D5517C2A5282F8B5FE51C3AB298BEC8B6015BFDCDBCA733C17E22C |
| sha256.hpp | B670525A491F18DAAFB650B3BD65C1426AB60BC0835E02DA0190C273608A658A |
| isolated worker binary | 6CD66A7B37028C6BFD24C8190E46A7F9074AAE1E9561B63302555D60D78EC06D |

Qualified binary:

D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/hh06_worker_lineage_transition_fix_audit_v1/qualified_source_v1/build/cfd_ancf_ancf_kernel_worker_lineage_transition_qualified

Build recipe was an isolated CMake target derived from the repository C++
worker target, using C++17, Release, and -Wall -Wextra -Wpedantic -Werror
under GCC 11.4.0/CMake 3.22.1 in Ubuntu 22.04 WSL.

## State-machine change

The previous worker used sequence modulo 2 to decide whether a request was a
same-window retry or a next-window request. This incorrectly rejected sequence
6 after a five-iteration window committed at sequence 5.

The isolated patch removes that parity branch. For every request after the
first:

- Same-window retry: global_step, bridge_step, integer_tick, time_s, and dt_s
  all equal the last accepted physical identity.
- Next-window first request: global_step and bridge_step increase by one,
  integer_tick advances by the exact dt_s tick, time_s increases by exactly
  dt_s, and dt_s is unchanged.
- With implicit retry enabled, only those two identities are accepted.
- With implicit retry disabled, only the exact next-window identity is accepted.
- Sequence/request/transaction duplicate and monotonic checks remain active.

physical_window_id is not a separate wire field in this protocol; it is
represented by the validated tuple
(global_step, bridge_step, integer_tick, time_s, dt_s).

## Lineage transition table

| physical window | request sequences | physical identity | rollbacks | commit | response headers |
|---:|---|---|---:|---|---:|
| 1 | 1, 2, 3, 4, 5 | (1, 1, 200000, 0.0002, 0.0002) | 4 | after sequence 5 | 5/5 |
| 2 | 6, 7, 8, 9, 10 | (2, 2, 400000, 0.0004, 0.0002) | 4 | after sequence 10 | 5/5 |

The eight rollback restores returned the checkpoint physical state exactly
(q, qdot, and qddot), and all ten response states were finite.

## Transport identity audit

| identity | observed values | result |
|---|---|---|
| sequence | 1..10 | strictly increasing |
| request_id | 910001..910010 | strictly increasing |
| transaction_id | 1910001..1910010 | strictly increasing |
| duplicate request/transaction IDs | none | duplicate guard retained |
| accepted windows | 2/2 | PASS |
| rollback count | 8 total, 4 per window | PASS |
| response headers | 10/10 | PASS |

## Qualification boundary

The test used the production HH06 KernelModel and KernelStepRequest serializer
through PersistentHH06KernelBackend and GenericStructuralCoordinator. It
started only the isolated worker and sent two physical windows with five
requests per window. It did not initialize preCICE, start Fluid_0000, run
OpenFOAM, advance CFD time, or create OpenFOAM time directories.

Raw machine-readable evidence:

D:/研二文件/开题准备/CFD_ANCF_VIV/runtime/hh06_worker_lineage_transition_fix_audit_v1/lineage_transition_test_result.json

## Final answers

- Lineage transition table: PASS.
- Accepted window count: 2/2.
- Rollback count: 8.
- Sequence/request/transaction monotonicity: PASS.
- WORKER_LINEAGE_WINDOW_TRANSITION_PARITY_DEFECT: absent in the patched isolated worker.
- Production worker deployment: not performed.
- CFD/preCICE runtime qualification: not performed.

The isolated fix is ready for human review; it must not be deployed to
slice0000 or used for a real FSI run without separate authorization.
