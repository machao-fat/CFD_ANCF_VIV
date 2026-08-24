from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ForceArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImmutableForceArtifact:
    path: Path
    run_id: str
    case_id: str
    step: int
    slice_id: int
    time_tick: int
    sha256: str
    size: int
    schema: str = "stage4f-force-artifact-1.0"

    @classmethod
    def create(cls, source: str | Path, destination: str | Path, *, run_id: str, case_id: str, step: int, slice_id: int, time_tick: int) -> "ImmutableForceArtifact":
        src, dst = Path(source), Path(destination)
        if not src.is_file() or dst.exists():
            raise ForceArtifactError("source missing or destination already exists")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
        tmp.write_bytes(src.read_bytes())
        tmp.replace(dst)
        digest = hashlib.sha256(dst.read_bytes()).hexdigest()
        return cls(dst, run_id, case_id, int(step), int(slice_id), int(time_tick), digest, dst.stat().st_size)

    def validate(self, *, run_id: str, case_id: str, step: int, slice_id: int, time_tick: int) -> dict[str, Any]:
        if (run_id, case_id, int(step), int(slice_id), int(time_tick)) != (self.run_id, self.case_id, self.step, self.slice_id, self.time_tick):
            raise ForceArtifactError("force artifact identity mismatch")
        if not self.path.is_file() or self.path.stat().st_size != self.size:
            raise ForceArtifactError("force artifact size changed or is missing")
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        if digest != self.sha256:
            raise ForceArtifactError("force artifact content hash changed")
        return {"path": str(self.path.resolve()), "sha256": digest, "size": self.size, "schema": self.schema,
                "run_id": self.run_id, "case_id": self.case_id, "global_step": self.step,
                "slice_id": self.slice_id, "time_tick": self.time_tick, "immutable": True}
