"""Add the retained Ur=8 final 240 s checkpoint to the cleanup hash manifest."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(r"D:\研二文件\开题准备\CFD_ANCF_VIV").resolve()
MANIFEST = ROOT / "results/cleanup/stage3_v8_checkpoint_hash_manifest.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["field_hashes"]
    known = {row["relative_path"] for row in records}
    roots = [
        ("Ur8_final_240_case", ROOT / "cases/openfoam/single_dof_free_v6_to200/240"),
        ("Ur8_final_240_structure", ROOT / "results/04_sdof_corrected_campaign/Ur8p0_v7_to260/sdof_checkpoint.json"),
    ]
    added = 0
    for label, path in roots:
        paths = sorted(path.rglob("*")) if path.is_dir() else [path]
        for file in paths:
            if not file.is_file():
                continue
            relative = file.relative_to(ROOT).as_posix()
            if relative in known:
                continue
            records.append({"label": label, "relative_path": relative, "absolute_path": str(file), "status": "present", "bytes": file.stat().st_size, "sha256": digest(file)})
            known.add(relative)
            added += 1
    payload["generated_utc"] = datetime.now(timezone.utc).isoformat()
    payload["augmentation"] = "retained Ur=8 final effective 240 s checkpoint and structure checkpoint"
    MANIFEST.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "augmented", "added_records": added, "total_records": len(records)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
