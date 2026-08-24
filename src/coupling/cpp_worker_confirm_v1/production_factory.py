"""Import-safe production factory for the Stage100 C++ confirm.

The factory owns only construction and identity wiring.  External processes
are started by the injected backend's ``start``/first publish lifecycle after
``CppConfirmRun.start`` has passed the explicit real-process contract guard.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Callable, Mapping

from coupling.multi_slice_driver.contract import SliceExchangePaths
from coupling.multi_slice_mapping.mapping import RuntimeConfig, SliceManifest

from .contracts import ContractError, CppConfirmContract
from .real_coordinator import LaunchGuard
from .real_slice_adapter import PersistentOpenFOAMSliceAdapter, validate_slice_factory
from .lifecycle import ResidentCppWorkerLifecycle


class ProductionFactoryError(RuntimeError):
    """Fail-closed production factory error."""


def bind_cpp_worker_lifecycle(adapter: Any) -> ResidentCppWorkerLifecycle:
    """Return the coordinator-facing lifecycle for one resident C++ adapter.

    The returned object is safe to pass as both ``CppConfirmRun.worker`` and
    the adapter argument to ``commit_step_with_cpp_adapter``.  Consequently
    the coordinator's start boundary and the adapter's transport calls share
    one underlying worker process and cannot accidentally double-start it.
    """
    try:
        return ResidentCppWorkerLifecycle(adapter)
    except Exception as exc:
        raise ProductionFactoryError(str(exc)) from exc


def build_persistent_slice_factory(*, contract: CppConfirmContract,
                                   authorization: str | None,
                                   manifest: SliceManifest,
                                   runtime_config: RuntimeConfig,
                                   paths_factory: Callable[[int, Path], SliceExchangePaths],
                                   seed_factory: Callable[[int], Any],
                                   backend_factory: Callable[[int, Path], Any]) -> Callable[[int, Path], PersistentOpenFOAMSliceAdapter]:
    """Create a validated, lazy three-slice factory.

    ``backend_factory`` is deliberately injected so offline tests can use a
    fake backend and the real path can bind the existing
    ``PersistentOpenFOAMSliceProcess`` without changing that protected module.
    No backend is constructed while this function validates its arguments.
    """
    if contract.slice_count != 3:
        raise ProductionFactoryError("Stage100 production requires exactly three slices")
    if not contract.allow_real_external_processes:
        raise ContractError("production slice factory requires an enabled real-process contract")
    try:
        LaunchGuard.require(contract, authorization)
    except ContractError:
        raise
    if not isinstance(manifest, SliceManifest) or len(manifest.slices) != 3:
        raise ProductionFactoryError("frozen three-slice manifest is required")
    if manifest.case_id != contract.case_id:
        raise ProductionFactoryError("manifest case_id does not match contract")
    if not callable(paths_factory) or not callable(seed_factory) or not callable(backend_factory):
        raise ProductionFactoryError("all production factories must be callable")
    try:
        if len(inspect.signature(backend_factory).parameters) < 2:
            raise ProductionFactoryError("backend_factory must accept slice_id and runtime path")
    except (TypeError, ValueError) as exc:
        raise ProductionFactoryError("backend_factory signature is unavailable") from exc

    def factory(slice_id: int, runtime_path: Path) -> PersistentOpenFOAMSliceAdapter:
        sid = int(slice_id)
        if sid not in {0, 1, 2}:
            raise ProductionFactoryError("slice_id is outside the exact three-slice scope")
        root = Path(runtime_path).resolve()
        if contract.runtime.resolve() not in root.parents:
            raise ProductionFactoryError("slice runtime escaped contract runtime")
        backend = backend_factory(sid, root)
        return PersistentOpenFOAMSliceAdapter(
            backend=backend, manifest=manifest, runtime_config=runtime_config,
            paths=paths_factory(sid, root), initial_seed=seed_factory(sid), slice_id=sid)

    validate_slice_factory(factory)
    return factory


__all__ = ["ProductionFactoryError", "build_persistent_slice_factory", "bind_cpp_worker_lifecycle"]


def build_existing_openfoam_backend_factory(*, contract: CppConfirmContract,
                                             manifest: SliceManifest,
                                             runtime_config: RuntimeConfig,
                                             case_by_slice: Mapping[int, Path],
                                             exchange_root: Path,
                                             library: Path,
                                             run_id: str,
                                             persistent_options: Mapping[str, Any] | None = None) -> Callable[[int, Path], Any]:
    """Bind the existing persistent OpenFOAM process without changing it.

    Cases must already be independently staged and audited under the new
    runtime.  Construction is lazy; ``PersistentOpenFOAMSliceProcess`` does
    not launch WSL until its first seed/target publication.
    """
    if set(case_by_slice) != {0, 1, 2}:
        raise ProductionFactoryError("exactly three staged OpenFOAM cases are required")
    if not Path(library).is_file():
        raise ProductionFactoryError("ancfFileMotion library is missing")
    roots = {sid: Path(case_by_slice[sid]).resolve() for sid in range(3)}
    if any(not root.is_dir() for root in roots.values()):
        raise ProductionFactoryError("a staged OpenFOAM case directory is missing")
    options = dict(persistent_options or {})

    def backend_factory(slice_id: int, runtime_path: Path) -> Any:
        sid = int(slice_id)
        if sid not in roots:
            raise ProductionFactoryError("slice_id outside exact scope")
        from coupling.performance_optimization_v2.openfoam_persistent import PersistentOpenFOAMSliceProcess
        process = PersistentOpenFOAMSliceProcess(
            slice_id=sid, case=roots[sid], exchange_root=Path(exchange_root),
            manifest=manifest, runtime_config=runtime_config, library=Path(library),
            run_id=run_id,
            segment_end_time_s=contract.source_time_s + contract.steps * contract.global_dt_s,
            **options)
        process.stage100_runtime_path = str(Path(runtime_path).resolve())
        return process

    return backend_factory


__all__.append("build_existing_openfoam_backend_factory")
