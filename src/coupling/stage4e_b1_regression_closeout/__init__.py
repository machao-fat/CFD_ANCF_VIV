"""Stage 4E-B1-v2 regression closeout markers and audit contract."""

REQUIRED_CLOSEOUT_ARTIFACTS = (
    "process_inventory_before.json",
    "owned_process_registry.json",
    "owned_process_cleanup_audit.json",
    "process_inventory_after.json",
    "retained_process_handoff.json",
    "runtime_path_audit.json",
    "c_drive_write_diff.json",
)

__all__ = ["REQUIRED_CLOSEOUT_ARTIFACTS"]
