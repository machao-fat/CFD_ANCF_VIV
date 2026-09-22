"""In-place continuation launcher for the existing 40k moving-wall case.

This wrapper reuses the previously validated continuation participant and
only redirects its JSONL/summary outputs to new filenames inside the existing
``moving_wall/structure`` directory.  It does not change the SDOF integrator
or the preCICE data-exchange semantics.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


# This wrapper lives directly in ``CFD_ANCF_VIV/tools`` (rather than in a
# nested tool directory), so parents[1] is the project root.
PROJECT = Path(__file__).resolve().parents[1]
BASE_PARTICIPANT = (
    PROJECT
    / "tools"
    / "shiels_s5_k988_single_slice_free_fsi_long_development_resume_v4"
    / "sdof_precice_continuation_participant.py"
)


class ExistingRuntime:
    """Path-like facade that preserves old evidence and writes new records."""

    def __init__(self, root: Path, suffix: str) -> None:
        self.root = root
        self.suffix = suffix

    def exists(self) -> bool:
        # The imported participant uses this only as a rerun guard.  The
        # destination files are deliberately new, so the guard is false.
        return False

    def mkdir(self, *args, **kwargs) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def __truediv__(self, name: str) -> Path:
        mapping = {
            "events.jsonl": f"events_{self.suffix}.jsonl",
            "structure_summary.json": f"structure_summary_{self.suffix}.json",
            "progress.json": f"progress_{self.suffix}.json",
        }
        return self.root / mapping.get(name, name)


def load_module():
    spec = importlib.util.spec_from_file_location("validated_sdof_continuation", BASE_PARTICIPANT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load validated participant: {BASE_PARTICIPANT}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves postponed annotations through sys.modules while
    # the imported continuation module is being executed.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--vertex-count", type=int, default=104)
    parser.add_argument("--suffix", default="resume_250_to_300")
    args = parser.parse_args()

    if not BASE_PARTICIPANT.is_file():
        raise FileNotFoundError(BASE_PARTICIPANT)
    module = load_module()
    runtime = ExistingRuntime(args.runtime_root, args.suffix)
    forwarded = SimpleNamespace(
        config=args.config,
        contract=args.contract,
        runtime=runtime,
        vertex_count=args.vertex_count,
    )
    return int(module.run_participant(forwarded))


if __name__ == "__main__":
    raise SystemExit(main())
