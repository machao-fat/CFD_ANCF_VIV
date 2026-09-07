"""Canonical WSL paths for preCICE socket exchange directories.

The conversion is deliberately type-aware: a Windows drive path is converted
once, while already-Linux paths are retained.  Relative paths are resolved in
the caller's current platform before classification.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path, PurePosixPath


_WINDOWS_DRIVE = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def canonical_wsl_path(path: str | Path) -> str:
    """Return a canonical Linux path suitable for a WSL-side preCICE config."""
    raw = str(path)
    if not raw:
        raise ValueError("path must not be empty")
    if raw.startswith("/"):
        # Includes /mnt/<drive>/..., /home/... and any valid Linux absolute path.
        return os.path.normpath(raw)
    match = _WINDOWS_DRIVE.match(raw)
    if match:
        drive, tail = match.groups()
        return "/mnt/" + drive.lower() + "/" + tail.replace("\\", "/")
    resolved = Path(raw).resolve()
    resolved_text = str(resolved)
    if resolved_text.startswith("/"):
        return os.path.normpath(resolved_text)
    match = _WINDOWS_DRIVE.match(resolved_text)
    if match:
        drive, tail = match.groups()
        return "/mnt/" + drive.lower() + "/" + tail.replace("\\", "/")
    raise ValueError(f"cannot classify path for WSL conversion: {path!r}")


def socket_directory_preflight(path: str | Path) -> dict[str, object]:
    """Check the parent used by preCICE before it attempts to create sockets."""
    canonical = canonical_wsl_path(path)
    if os.name == "nt" and canonical.startswith("/"):
        # pathlib on Windows correctly classified the *input* above, but cannot
        # stat a Linux namespace path.  Check the target namespace exactly
        # once through WSL rather than reinterpret /mnt/... as \mnt\....
        parent_text = str(PurePosixPath(canonical).parent)
        parent_exists = subprocess.run(
            ["wsl.exe", "-d", "Ubuntu-22.04", "--", "test", "-d", parent_text],
            capture_output=True,
        ).returncode == 0
        parent_writable = parent_exists and subprocess.run(
            ["wsl.exe", "-d", "Ubuntu-22.04", "--", "test", "-w", parent_text, "-a", "-x", parent_text],
            capture_output=True,
        ).returncode == 0
        return {
            "canonical_socket_path": canonical,
            "parent": parent_text,
            "parent_exists": parent_exists,
            "parent_writable": parent_writable,
            "status": "PASS" if parent_exists and parent_writable else "FAIL",
        }
    parent = Path(canonical).parent
    return {
        "canonical_socket_path": canonical,
        "parent": str(parent),
        "parent_exists": parent.is_dir(),
        "parent_writable": os.access(parent, os.W_OK | os.X_OK) if parent.is_dir() else False,
        "status": "PASS" if parent.is_dir() and os.access(parent, os.W_OK | os.X_OK) else "FAIL",
    }
