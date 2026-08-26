"""Explicit lifecycle wrapper for the resident C++ campaign adapter.

The wrapper is intentionally small: numerical state and IPC validation remain
in :mod:`cpp_adapter`, while this module owns exactly one start and one
terminal cleanup boundary for a bounded segment.
"""

from __future__ import annotations

from typing import Any


class LifecycleError(RuntimeError):
    """A worker lifecycle transition violated the bounded-run contract."""


class ResidentCppWorkerLifecycle:
    """Adapt an adapter's ``start``/``shutdown`` API to ``start``/``stop``.

    Duplicate starts are rejected because they would create a second worker
    for the same segment.  Stops are idempotent so coordinator error paths can
    safely clean up without masking the original failure.
    """

    def __init__(self, adapter: Any) -> None:
        if not callable(getattr(adapter, "start", None)):
            raise LifecycleError("resident adapter must provide start()")
        if not callable(getattr(adapter, "shutdown", None)) and not callable(getattr(adapter, "stop", None)):
            raise LifecycleError("resident adapter must provide shutdown() or stop()")
        self.adapter = adapter
        self._started = False
        self._stopped = False

    def start(self) -> None:
        if self._started or self._stopped:
            raise LifecycleError("resident C++ worker duplicate or terminal start")
        try:
            self.adapter.start()
        except Exception:
            self._stopped = True
            raise
        self._started = True

    def stop(self) -> None:
        if self._stopped:
            return
        if not self._started:
            self._stopped = True
            return
        shutdown = getattr(self.adapter, "shutdown", None)
        try:
            (shutdown if callable(shutdown) else self.adapter.stop)()
        except Exception:
            # Keep the wrapper retryable so a coordinator can perform one
            # final forced cleanup and still observe any residual.
            raise
        self._stopped = True
        self._started = False

    shutdown = stop

    @property
    def start_count(self) -> int:
        return int(getattr(self.adapter, "start_count", 0))

    @property
    def owned_residual(self) -> int:
        return int(getattr(self.adapter, "owned_residual", 0))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.adapter, name)


__all__ = ["LifecycleError", "ResidentCppWorkerLifecycle"]
