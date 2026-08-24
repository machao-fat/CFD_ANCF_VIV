from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Mapping

from src.coupling.multi_slice_driver import MultiSliceConfig, MultiSliceScheduler, SliceSpec
from src.coupling.multi_slice_driver.mocks import MockSliceProcess, MockStructureAdapter


def make_harness(
    *, n_slices: int = 2, faults: Mapping[int, str] | None = None,
    structure_fault: str | None = None, timeout_s: float = 0.05,
    root: Path | None = None,
):
    owned = None
    run_root = Path(tempfile.mkdtemp()) if root is None else root
    assert run_root is not None
    specs = tuple(
        SliceSpec(slice_id=index, s_ref_m=0.25 * index, slice_length_m=0.25, unit_span_m=1.0)
        for index in range(n_slices)
    )
    config = MultiSliceConfig(
        case_id="mock_case", dt_s=0.01, timeout_s=timeout_s,
        specs=specs, start_time_s=0.0,
    )
    structure = MockStructureAdapter(specs, fault=structure_fault)
    case_root = run_root / "cases"
    processes = [
        MockSliceProcess(
            spec, case_id=config.case_id, exchange_root=run_root / "exchange",
            case_root=case_root, fault=(faults or {}).get(spec.slice_id),
        )
        for spec in specs
    ]
    scheduler = MultiSliceScheduler(
        config=config, exchange_root=run_root / "exchange", structure=structure,
        slice_processes=processes, checkpoint_root=run_root / "checkpoints",
        case_root=case_root,
    )
    return scheduler, structure, processes, run_root
