"""Validation-only worker initialize/shutdown probe; no physical step."""
from __future__ import annotations

from pathlib import Path
import argparse
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from coupling.cpp_worker_persistent_ipc_v1.protocol import (  # noqa: E402
    HEADER,
    MAGIC,
    MESSAGE_INITIALIZE,
    MESSAGE_INITIALIZE_ACK,
    MESSAGE_SHUTDOWN,
    encode_control,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--worker",
        default=str(REPO / "runtime/coupling_validation/REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1/bin/ancf_worker.exe"),
    )
    args = parser.parse_args()
    exe = Path(args.worker).resolve()
    process = subprocess.Popen(
        [str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(encode_control(MESSAGE_INITIALIZE))
    process.stdin.flush()
    header = process.stdout.read(HEADER.size)
    if len(header) != HEADER.size:
        raise RuntimeError("missing initialize response header")
    magic, length, message_type = HEADER.unpack(header)
    body = process.stdout.read(length)
    if magic != MAGIC or message_type != MESSAGE_INITIALIZE_ACK or len(body) != length:
        raise RuntimeError("invalid initialize acknowledgement")
    process.stdin.write(encode_control(MESSAGE_SHUTDOWN))
    process.stdin.flush()
    process.stdin.close()
    return_code = process.wait(timeout=20)
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    print("WORKER_HANDSHAKE=PASS")
    print(f"WORKER_SHUTDOWN_RC={return_code}")
    print(f"WORKER_STDERR_BYTES={len(stderr.encode('utf-8'))}")
    if return_code != 0:
        raise RuntimeError("worker shutdown returned nonzero")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
