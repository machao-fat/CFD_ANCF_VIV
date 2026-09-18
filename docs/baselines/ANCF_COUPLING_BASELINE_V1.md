# ANCF_COUPLING_BASELINE_V1

## Baseline identity

`ANCF_COUPLING_BASELINE_V1` freezes the structural-side software stack at
production commit `dfb1a3e7e92220a2e4c9400317de372e637095eb` (parent
`e85c751d92d50483b7ea0f744c45d13af5d340ac`). The commit message is `Add
static terminal-state observability`.

This is the frozen structural-side software baseline authorized for subsequent
controlled CFD-ANCF coupling development and validation. It is a development
and identity baseline, not a declaration that the ANCF solver has completed
independent validation.

The machine-readable inventory and status record are in
`ANCF_COUPLING_BASELINE_V1_MANIFEST.json`. The inventory records only the
current generic kernel/worker and coupling-path components. Historical
diagnostics, obsolete prototypes, test-only sources, runtime evidence,
generated binaries, and stage-specific continuation launchers are excluded.

## Frozen structural-side stack

The stack is grouped by runtime responsibility:

- The C++ ANCF kernel, persistent worker, in-process protocol/client support,
  wire schema, build contract, and hashing support are under
  `src/coupling/cpp_worker_persistent_ipc_v1/`.
- Generic case/configuration and state preparation are provided by the
  `tools/precice_ancf_adapter_v1/` case-config, kinematics, participant,
  damping-preprocessor, and static-prestress modules. This includes both
  legacy and explicit section-property selection through the existing generic
  configuration contract.
- Single-slice and three-slice worker-backed preCICE participant launchers are
  included as coupling glue. Longer continuation launchers and historical
  stage runners remain scenario-specific and are not part of this baseline
  identity.
- Generic multi-slice force/displacement mapping and exchange orchestration
  are under `src/coupling/multi_slice_mapping/` and
  `src/coupling/multi_slice_driver/`.
- The reusable ANCF-to-preCICE envelope, barrier, mapping, storage, guard, and
  worker-adapter contract is under
  `src/coupling/precice_ancf_adapter_v1/`.

The exact path, SHA-256, role, tracking state, and classification for every
frozen file are authoritative only from the JSON manifest.

## Validation state frozen at this baseline

The following states are retained without reinterpretation:

| Area | Retained status |
|---|---|
| A current-line | `PASS` |
| B V1 | `FAIL` retained |
| B V1.1 | `PASS`; current-line B closed |
| C numerical V1 | identity evidence incomplete retained |
| C identity closure | `PASS`; current-line C `CLOSED` |
| D V1 | `FAIL` retained |
| D V1.1 | `FAIL` retained |
| D V1.2 | `PASS`; current-line D `CLOSED` |
| E historical predecessors | retained |
| E current-line replacement V1 | `PASS`; current-line E `CLOSED` |
| F historical | `PASS` retained |
| F current-line V1 | `STOPPED_BEFORE_PROTOCOL` retained |
| F current-line V1.1 | `FAIL` retained |
| F current-line V1.2 | `PASS`; current-line F `CLOSED` |
| Historical G1-V1.2 | `FAIL` retained |
| G1 current-line V1 | `FAIL / G1_PREFLIGHT_IDENTITY_MISMATCH`; numerical execution `0` |
| G1 harness qualifications | predecessor `FAIL` and later `PASS/READY` states retained |
| G1 current-line V1.1 | `FAIL / G1_STATIC_SOLVE_FAIL` |
| G1 current-line validation | `NOT_CLOSED` |
| ANCF independent structural validation | `NOT_CLOSED` |
| Terminal-state observability V1.2 | `PASS` |

The unresolved G1 V1.1 mechanism remains `STATIC_NEWTON_DID_NOT_CONVERGE` at
mesh 136, with the documented Newton residual plateau unresolved. The
observability commit does not change that status.

This baseline must not be described as a fully independently validated ANCF
structural solver. In particular, it must not be described as G1 passed, CFD
validated, CFD-ANCF coupling validated, FSI validated, or VIV validated.

## Authorized downstream use

Subject to each later case's own protocol and identity checks, this baseline
may be used for:

- structural-side coupling development;
- single-slice CFD-ANCF smoke tests;
- multi-slice and three-slice coupling;
- force mapping and displacement/motion mapping validation;
- preCICE lifecycle validation;
- controlled CFD-ANCF FSI development; and
- subsequent VIV validation work.

These permissions authorize development against the frozen structural-side
identity. They do not waive case-specific numerical gates or close the G1
limitation.

## Baseline change policy

From `ANCF_COUPLING_BASELINE_V1` onward, a coupling case must not silently
modify the frozen structural production stack. The required transition for a
future production change is:

`issue identified -> isolated patch -> bounded regression -> focused commit -> new baseline version or explicit baseline successor`

The following shortcut is prohibited:

`coupling failure -> ad-hoc ANCF modification -> continue production run without new identity`

Any changed production source, worker, wire contract, or coupling-path
component must therefore receive a new source identity and an explicit
successor decision before use.

## Future coupling-case provenance contract

Every future formal coupling case should record at minimum:

- `ANCF_BASELINE_TAG`
- `ANCF_BASELINE_COMMIT`
- `ANCF_PRODUCTION_MANIFEST_SHA256`
- `PRECICE_CONFIG_SHA256`
- `STRUCTURAL_CASE_CONFIG_SHA256`
- `OPENFOAM_CASE_IDENTITY` or an equivalent case-manifest identity
- participant source/config identities
- slice count and slice length
- force dimensional convention and force mapping convention
- motion/displacement mapping convention

The current baseline task does not modify any existing case, preCICE
configuration, OpenFOAM case, participant configuration, or runtime evidence.

## Scope and exclusions

The inventory is a source identity freeze, not a claim that every file in the
repository is production code. In particular, it excludes historical
validation reports, forensic/diagnostic executables, test fixtures, generated
runtime directories, old MATLAB-only alternatives, and scenario-specific
continuation scripts unless they are part of the generic path described in the
manifest. They remain untouched in the working tree.

No numerical case, G1 campaign, OpenFOAM run, preCICE run, CFD/FSI run, or VIV
run was executed for this freeze.
