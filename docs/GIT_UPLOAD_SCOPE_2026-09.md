# Git upload scope — 2026-09

## Purpose

This commit records the accumulated CFD–ANCF development work that is
appropriate for the public source repository.  It does not publish local
OpenFOAM campaign output or numerical time histories.

## Repository state

- Repository: `CFD_ANCF_VIV`
- Remote: `https://github.com/machao-fat/CFD_ANCF_VIV.git`
- Upload branch: `validation/g1-terminal-diagnostic-serialization-repair-v1`
- Base commit before this upload: `8443209`
- Upload policy: normal commit and normal push; no force push and no `main`
  branch rewrite.

## Included

- Python/C++ coupling and persistent-worker source changes.
- SHM1 protocol codec and HH06 Structure_0000 wrapper materials.
- Checkpoint/rollback, protocol, and validation test sources.
- Offline audit reports, contracts, README/documentation, and reproducibility
  scripts.

The tracked source changes in this upload include:

1. Keeping a physical checkpoint alive across repeated implicit rollback/retry
   operations, clearing it only after commit.
2. Supplying required initial Displacement data before preCICE initialization.
3. Adding the SHM1 v1 hydrodynamic-region model, validation, and wire
   serialization while preserving the empty-region legacy payload.

`ancf_worker_main.cpp` had a stale worktree status marker but its content hash
was identical to `HEAD`; no content change was included for that file.

## Excluded (not deleted)

The following remain on the local machine and are intentionally not staged:

- `cases/openfoam/**`: local OpenFOAM campaign directories, mesh copies,
  time directories, logs, post-processing data, and restart artifacts.  The
  current local inventory is approximately 101,237 files / 5.58 GiB.
- `runtime/`, solver caches, build products, core dumps, and generated logs.
- `presentation/`, `rendered_slides/`, `GROUP_MEETING_*`, and generated
  presentation data exports; these are local deliverables rather than solver
  source.
- Temporary `tools/**/_tmp_*` scripts.
- Numerical outputs that cannot be reconstructed from the committed source and
  contract files.

The `.gitignore` rule for `cases/openfoam/**` is a repository-level safeguard
against accidentally publishing another multi-gigabyte campaign.  A reusable
case template can still be added intentionally with `git add -f` after review.

No excluded file was removed or altered by this upload.

## Verification performed before push

- Reviewed branch, remote, and working-tree state.
- Confirmed the three substantive tracked source diffs with `git diff`.
- Checked that no CFD, preCICE, OpenFOAM, or ANCF calculation was started by
  the upload operation.
- After staging, `git diff --cached --check` and the staged-file inventory are
  used as the final commit gate.
