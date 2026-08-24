from __future__ import annotations
import inspect
from typing import Any
from ..multi_slice_driver.scheduler import MultiSliceScheduler
from ..checkpoint.atomic_checkpoint import AtomicCheckpointManager

REQUIRED_SCHEDULER_HOOKS=("stabilization_hook","run_id")
REQUIRED_CHECKPOINT_FIELDS=("raw_slice_forces_N","applied_slice_forces_N","stabilizer_state","time_tick","run_id")

def audit_interfaces() -> dict[str, Any]:
    scheduler_signature=inspect.signature(MultiSliceScheduler.__init__)
    scheduler_missing=[name for name in REQUIRED_SCHEDULER_HOOKS if name not in scheduler_signature.parameters]
    prepare=inspect.signature(AtomicCheckpointManager.prepare)
    checkpoint_missing=[name for name in REQUIRED_CHECKPOINT_FIELDS if name not in prepare.parameters]
    run_source=inspect.getsource(MultiSliceScheduler.run_step)
    order={"loads_consumed":run_source.find("SchedulerState.LOADS_CONSUMED"),
           "structure_correct":run_source.find("self.structure.correct_all"),
           "checkpoint_prepare":run_source.find("self.checkpoint_manager.prepare")}
    valid_order=0 <= order["loads_consumed"] < order["structure_correct"] < order["checkpoint_prepare"]
    passed=not scheduler_missing and not checkpoint_missing and valid_order
    return {"scheduler_missing_hooks":scheduler_missing,"checkpoint_missing_fields":checkpoint_missing,
            "existing_order":order,"existing_order_valid":valid_order,"passed":passed,
            "classification":"production_interface_extension_required" if not passed else "adapter_attachable"}

def require_probe_ready() -> None:
    result=audit_interfaces()
    if not result["passed"]:
        raise RuntimeError("stabilized adapter probe blocked: production interface extension required")
