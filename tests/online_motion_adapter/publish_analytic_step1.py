from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path


def atomic_text(path: Path, text: str) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    coupling = Path(sys.argv[1])
    delay_s = float(sys.argv[2])
    time_s = 0.0025
    omega = 1.00530964914873
    amplitude = 0.1
    y = amplitude * math.sin(omega * time_s)
    vy = amplitude * omega * math.cos(omega * time_s)
    ay = -amplitude * omega**2 * math.sin(omega * time_s)
    import time
    time.sleep(delay_s)
    payload = coupling / "motion.csv"
    text = (
        "schema_version,step,coupling_iteration,time_s,slice_id,s_ref_m,x_m,y_m,z_m,"
        "vx_mps,vy_mps,vz_mps,ax_mps2,ay_mps2,az_mps2\n"
        f"0.1.0,1,0,{time_s:.17g},0,0,0,{y:.17g},0,0,{vy:.17g},0,0,{ay:.17g},0\n"
    )
    atomic_text(payload, text)
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    marker = {
        "coupling_iteration": 0,
        "kind": "motion",
        "payload": payload.name,
        "row_count": 1,
        "schema_version": "0.1.0",
        "sha256": digest,
        "step": 1,
        "time_s": time_s,
    }
    atomic_text(coupling / "motion_ready", json.dumps(marker, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
