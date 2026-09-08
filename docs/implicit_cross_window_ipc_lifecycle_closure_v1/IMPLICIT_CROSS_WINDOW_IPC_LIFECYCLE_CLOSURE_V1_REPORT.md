# IMPLICIT_CROSS_WINDOW_IPC_LIFECYCLE_CLOSURE_V1_REPORT

## Scope and immutable evidence

- Frozen OpenFOAM adapter: SHA256 `6064f098a7913c7ca65ed021beeca0159ab8c62509fb2bcca54351c0b55d8973`; patches `0001/0002/0004/0005`; preCICE 3.4.1; OpenFOAM Foundation 10.
- The historical 0.05 s implicit runtime and every historical gate were read only. Its Git baseline was dirty; the new formal runtime records the actual launcher, participant, worker hashes, Git-status digest, and relevant source diff in `running_code_relevant.diff` rather than representing it as a commit-only reproduction.
- No explicit 0.05 s rerun and no run longer than the single authorized two-window qualification were launched.

## A — return-code 16 source diagnosis

`return 16` has several fail-closed uses in `ancf_worker_main.cpp`; the applicable historical branch was the opt-in implicit odd-sequence branch. After the accepted retry correction at wire sequence 4, `lineage_mode == 2`. The next legal request was window-2 prediction: wire sequence 5, global/bridge step 2, tick `10000000`, time `0.010 s`. The old branch treated *every* odd sequence in that mode as another same-window retry and required the window-1 identity (`step=1`, `tick=5000000`, `time=0.005 s`), then returned 16 before it could encode a response.

- Last successful historical frame: wire sequence 4, request ID 100004, transaction ID 200004, window 1 correction, `tau=0.005 s`; return code 0.
- First failed historical request: predicted wire sequence 5 for window 2 (`step=2`, `bridge=2`, `tick=10000000`, `tau=0.010 s`). The old runtime did not persist a raw binary request before `worker.step()`, so this identity is deterministically reconstructed from the immutable Python request factory and event ledger, not misrepresented as a retained raw frame.
- The worker stderr was empty because that historical 16 branch did not emit a diagnostic line. The branch condition, request identity, and exit code together identify it exactly.

## B — minimal protocol fix and regression

The worker now accepts exactly two states after an implicit retry correction: a retry with the same physical identity or a next-window prediction with step/bridge/tick/time advanced by one frozen `dt`. It still rejects every other identity and retains non-restorable, monotonic wire/request/transaction identifiers. The contract is versioned at `tools/implicit_cross_window_ipc_lifecycle_closure_v1/implicit_cross_window_ipc_lifecycle_contract_v1.json`.

Fresh real-worker, no-CFD regression (`real_worker_multiwindow_regression_002`) passed:

| Check | Result |
|---|---:|
| C++ worker physical windows committed | 3/3 |
| rollback/restore cycles | 9 |
| globally contiguous unique wire sequences | 1–24 |
| same-input retry | deterministic |
| different-input trial isolation | PASS |
| worker exit / owned residual | 0 / 0 |

The unchanged explicit transport also passed a fresh real-worker three-window regression (`real_worker_explicit_regression_001`): 3/3 commits, wires 1–6, worker exit 0. Neither regression starts OpenFOAM or preCICE Fluid.

## C — centralized preflight

The existing authoritative launcher, not a duplicate launcher, now has an explicit two-window-only mode. Before CFD construction it requires the real-worker cross-window regression and writes a code-identity snapshot. The actual formal library remained the frozen adapter SHA256 above. The new C++ worker was a separately built executable at `runtime/implicit_cross_window_ipc_lifecycle_closure_v1/cpp_worker_build_001/cfd_ancf_ancf_kernel_worker`, SHA256 `cb0e63116ede3c17d79e256eb1833edcdff8574d178ac1bfc81d2bcc2fad0d06`.

All production preflight checks passed: three moving-mesh cases, precursor U/p/phi transfer, IPC identity, projected initial state, socket path, Quality V4, and the cross-window worker regression.

## D — authorized formal two-window result

The only formal retry used `parallel-implicit`, `dt=0.005 s`, two windows, OpenFOAM physical time `0.100 -> 0.110 s`, no-flow structure state, and fixed-point iterations 2–8 without acceleration.

| Window | Coupling time [s] | Iterations | final prediction/correction wire |
|---:|---:|---:|---:|
| 1 | 0.005 | 2 | 3 / 4 |
| 2 | 0.010 | 3 | 9 / 10 |

- Both windows committed exactly once; all participant return codes and the C++ worker return code were zero. The worker did not disconnect.
- Structure checkpoint writes/restores were 2/3; every structure post-restore hash equaled its checkpoint hash. Wire IDs were monotonic and unique through 10.
- `Quality V4`, Newton (4/4 prediction/correction records), force contract, and Generalized Force V2 passed. Maximum V2 utilization was `0.03559197967977198`.
- Final raw force [N per 1 m] by slice 0/1/2 was `(-989.6602683, 85.1725706)`, `(-956.7606067, 83.7826348)`, and `(-989.1859312, 85.1545305)` for `(Fx, Fy)`. Corresponding integrated structural forces [N] were `(-16494.3378049, 1419.5428433)`, `(-15946.0101122, 1396.3772472)`, and `(-16486.4321873, 1419.2421746)`.
- Maximum committed `(abs(ux), abs(vx))` by slice was `(4.3752704e-05 m, 6.6566520e-03 m/s)`, `(4.4393517e-05 m, 6.2416568e-03 m/s)`, and `(4.3741625e-05 m, 6.6571371e-03 m/s)`.

## E — immutable formal gate failure

`FORMAL_IMPLICIT_TWO_WINDOW = FAIL` remains immutable. Its first failed checks are `fluid_field_history_rollback` and `dynamic_mesh_rollback`; there was no numerical, process, or IPC failure.

The post-run trace shows why: the current auditor keys checkpoint events solely by `window_id`. The adapter emitted a second `CHECKPOINT_WRITE` for the next window-start state with `window_id=1`, physical time `0.105 s`, timeIndex 1; it emitted the corresponding restores as `window_id=2`. The original auditor overwrote the first window-1 checkpoint in its dictionary, then compared the time-0.100 restore to the wrong time-0.105 checkpoint and had no key for the time-0.105 restores. Direct trace comparison by the actual lifecycle state shows both correct pairs have equal U/p/phi/Uf/cellDisplacement/mesh-point fingerprints and equal time/timeIndex.

This is an event-correlation/audit-key defect, not proof of failed field or mesh rollback. Per task instruction, it was **not** patched, re-audited into PASS, or rerun after the formal runtime failed. The minimal follow-up is a separately reviewed audit-only change that correlates each restore to the chronological checkpoint generation (or exact checkpoint physical-time/timeIndex identity), never a dictionary keyed only by adapter `window_id`; then rerun the two-window qualification under a new authorization.

## Decision

- `CROSS_WINDOW_IPC_LIFECYCLE = PASS`.
- `FORMAL_IMPLICIT_TWO_WINDOW = FAIL` (immutable audit gate).
- `NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED`.

