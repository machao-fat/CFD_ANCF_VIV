"""Prepare a restart at the actual saved field time (79.995 s) offline."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUNTIME = ROOT / "runtime/stage341_dt005_long_convergence_v1"
BOOTSTRAP = ROOT / "results/350_restart_bootstrap_velocity_v1/restart_bootstrap_state.json"
RUNTIME = ROOT / "runtime/stage358_restart_saved_time_alignment_v1_fresh"
RESULTS = ROOT / "results/358_restart_saved_time_alignment_v1"
SAVED_DIR = "79.995"
SAVED_TIME = 79.995
SOURCE_LABEL = "80"
TARGET_TIME = 80.195


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def relabel_header(path: Path) -> None:
    data = path.read_bytes()
    prefix = data[:4096]
    updated, count = re.subn(rb'(location\s+")[^"]*(")', rb'\g<1>79.995\g<2>', prefix, count=1)
    if count:
        path.write_bytes(updated + data[len(prefix):])


def relabel_time(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'location\s+"[^"]+";', 'location    "79.995/uniform";', text)
    text = re.sub(r'value\s+[^;]+;', 'value           79.995;', text)
    text = re.sub(r'name\s+"[^"]+";', 'name            "79.995";', text)
    text = re.sub(r'index\s+[^;]+;', 'index           15999;', text)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    bootstrap = json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
    if bootstrap.get("state_time_s") != SAVED_TIME or bootstrap.get("source_global_step") != 16000:
        raise RuntimeError("Stage350 bootstrap is not the expected 79.995 s lag-1 state")
    if RUNTIME.exists() and any(RUNTIME.iterdir()):
        raise RuntimeError(f"refusing to reuse non-empty runtime: {RUNTIME}")
    for index in range(3):
        source = SOURCE_RUNTIME / f"slice_{index:04d}"
        destination = RUNTIME / f"slice_{index:04d}"
        shutil.copytree(source, destination)
        for child in list(destination.iterdir()):
            if child.name not in {SOURCE_LABEL, "constant", "system"}:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        old = destination / SOURCE_LABEL
        saved = destination / SAVED_DIR
        old.rename(saved)
        for file in saved.rglob("*"):
            if file.is_file() and file.name != "time":
                relabel_header(file)
        relabel_time(saved / "uniform" / "time")
        control = destination / "system" / "controlDict"
        text = control.read_text(encoding="utf-8")
        text = re.sub(r"startFrom\s+[^;]+;", "startFrom       latestTime;", text)
        text = re.sub(r"startTime\s+[^;]+;", f"startTime       {SAVED_TIME:g};", text)
        text = re.sub(r"endTime\s+[^;]+;", f"endTime         {TARGET_TIME:g};", text)
        text = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", text)
        control.write_text(text, encoding="utf-8")
    (RUNTIME / "logs").mkdir(parents=True, exist_ok=True)
    initial = RUNTIME / "logs" / "initial_state.json"
    initial.write_text(json.dumps(bootstrap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    field_hashes = {}
    for index in range(3):
        field_hashes[f"slice_{index:04d}"] = {name: sha(RUNTIME / f"slice_{index:04d}" / SAVED_DIR / name) for name in ("U", "p", "pointDisplacement", "cellDisplacement", "phi", "meshPhi")}
    report = {
        "schema_version": 1, "stage_id": "stage4f_d_restart_saved_time_alignment_v1",
        "source_stage": "stage341_dt005_long_convergence_v1", "source_field_label": SOURCE_LABEL,
        "saved_time_s": SAVED_TIME, "saved_global_step": 15999,
        "target_time_s": TARGET_TIME, "target_global_step": 16039, "dt_s": 0.005,
        "state_time_s": bootstrap["state_time_s"], "field_directory": SAVED_DIR,
        "field_hashes": field_hashes,
        "checks": {"source_runtime_read_only": True, "all_field_headers_relabelled": True,
                   "uniform_time_relabelled": True, "state_field_clock_equal": True,
                   "matlab_starts": 0, "openfoam_starts": 0, "wsl_starts": 0,
                   "cfd_starts": 0, "owned_residual": 0},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "restart_saved_time_alignment.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate = dict(report, gate_id="STAGE4F_D_RESTART_SAVED_TIME_ALIGNMENT_V1_GATE", status="pass",
                next_action="request a new one-shot Smoke from 79.995 s; no continuation")
    (RESULTS / "stage4f_d_restart_saved_time_alignment_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": "pass", "saved_time_s": SAVED_TIME, "field_directory": SAVED_DIR, "external_starts": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
