from __future__ import annotations

from pathlib import Path
from typing import Any

from ..multi_slice_driver.ancf_adapter import ProductionANCFAdapter


class PersistentProductionANCFAdapter(ProductionANCFAdapter):
    """0.2.1 adapter whose native checkpoint is owned by the MATLAB worker."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._runner_checkpoint_token: str | None = None

    def export_runner_checkpoint(self, path: str | Path) -> None:
        exporter = getattr(self.runner, "save_checkpoint", None)
        if exporter is None:
            raise RuntimeError("persistent runner cannot export native checkpoint")
        response = exporter(path)
        token = response.get("checkpoint_token") if isinstance(response, dict) else None
        if token is not None:
            self._runner_checkpoint_token = str(token)

    def finalize_committed(self, checkpoint_token: object | None = None) -> None:
        token = self._runner_checkpoint_token
        if token is None:
            raise RuntimeError("MATLAB native checkpoint was not prepared before commit")
        finalizer = getattr(self.runner, "finalize_commit", None)
        if finalizer is None:
            raise RuntimeError("persistent runner does not expose finalize_commit")
        finalizer(token)
        super().finalize_committed(checkpoint_token)
        self._runner_checkpoint_token = None

    def discard_staged(self) -> None:
        discard = getattr(self.runner, "discard_staged", None)
        if discard is not None:
            discard()
        super().discard_staged()
        self._runner_checkpoint_token = None


__all__ = ["PersistentProductionANCFAdapter"]
