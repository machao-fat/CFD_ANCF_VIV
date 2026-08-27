from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .protocol import ExchangeMessage, ProtocolError


class TransportUnavailable(RuntimeError):
    pass


class FileTransport:
    """Reference transport used for A/B comparison; one JSONL record per message."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, message: ExchangeMessage) -> None:
        message.validate()
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(message.canonical_json() + "\n")
            stream.flush()

    def receive_all(self) -> list[ExchangeMessage]:
        if not self.path.exists():
            return []
        result = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            message = ExchangeMessage(**json.loads(line))
            message.validate()
            result.append(message)
        return result


class PreciceTransport:
    """Thin optional binding; no fallback to files when preCICE is absent."""

    def __init__(self, participant: str, config: str | Path):
        try:
            import precice  # type: ignore
        except ImportError as exc:
            raise TransportUnavailable("preCICE Python bindings are not installed") from exc
        self._precice = precice
        self.participant = participant
        self.config = str(config)

    @property
    def available(self) -> bool:
        return True

    def send(self, message: ExchangeMessage) -> None:
        raise NotImplementedError("bind write/read data to the pinned preCICE mesh in Stage 270")
