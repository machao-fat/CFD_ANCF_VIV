"""Fail-closed preparation and authorization guard for a fresh OpenFOAM .so.

This module never launches WSL by itself.  It prepares a new stage-local
source tree and records the exact output location so a later explicitly
authorized build cannot accidentally reuse a protected legacy artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .contracts import REAL_AUTHORIZATION_TOKEN, ContractError


class LibraryBuildError(RuntimeError):
    """A fresh library build precondition failed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _under(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def _copy_source_without_platform_links(source_tree: Path, destination: Path) -> None:
    """Copy source while materializing OpenFOAM's ``lnInclude`` links.

    The project source is a Linux checkout represented by dangling/reparse
    links on Windows.  The future WSL build needs regular files in its fresh
    tree, so links named after a root source file are materialized from that
    file rather than followed through Windows DrvFs.
    """
    for path in sorted(source_tree.rglob("*")):
        relative = path.relative_to(source_tree)
        target = destination / relative
        is_link = os.path.islink(str(path))
        # Windows may expose a dangling Linux symlink as a reparse point that
        # ``os.path.islink`` cannot identify.  OpenFOAM's lnInclude entries
        # are deterministic aliases to root-level headers/sources.
        if "lnInclude" in relative.parts and path.suffix in {".C", ".H", ".cpp", ".hpp"}:
            is_link = True
        if is_link:
            target.parent.mkdir(parents=True, exist_ok=True)
            fallback = source_tree / path.name
            if not fallback.is_file():
                raise LibraryBuildError(f"cannot materialize source link: {relative}")
            shutil.copy2(fallback, target)
            continue
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            shutil.copy2(path, target)


def prepare_fresh_library_build(*, project_root: Path, runtime: Path, results: Path,
                                source_tree: Path) -> dict[str, Any]:
    """Create an isolated source copy and immutable build manifest.

    No compiler, WSL process, OpenFOAM process or CFD process is started.
    ``runtime`` and ``results`` must be new directories; this prevents a
    partial build from being resumed or overwritten in the same runtime.
    """
    root = Path(project_root).resolve()
    runtime, results, source_tree = Path(runtime).resolve(), Path(results).resolve(), Path(source_tree).resolve()
    for name, path in (("runtime", runtime), ("results", results), ("source_tree", source_tree)):
        if root not in path.parents and path != root:
            raise LibraryBuildError(f"{name} escaped project root")
    if runtime.exists() and any(runtime.iterdir()):
        raise LibraryBuildError("fresh library runtime is not empty")
    if results.exists() and any(results.iterdir()):
        raise LibraryBuildError("fresh library results are not empty")
    if not source_tree.is_dir():
        raise LibraryBuildError("OpenFOAM source tree is missing")
    if "stage4f_three_slice_bridge_precision_repair_v1" in str(source_tree).lower():
        raise LibraryBuildError("protected legacy source/runtime cannot be used as build output")
    runtime.mkdir(parents=True, exist_ok=False)
    results.mkdir(parents=True, exist_ok=False)
    staged_source = runtime / "source" / "ancfFileMotion"
    _copy_source_without_platform_links(source_tree, staged_source)
    files = []
    for path in sorted(staged_source.rglob("*")):
        if path.is_file():
            relative = path.relative_to(staged_source).as_posix()
            if path.suffix.lower() in {".so", ".o", ".a"} or path.name.startswith("lib"):
                raise LibraryBuildError(f"staged source contains prebuilt artifact: {relative}")
            files.append({"path": relative, "sha256": _sha256(path), "size_bytes": path.stat().st_size})
    output = runtime / "lib" / "libancfFileMotion.so"
    plan = {
        "schema_version": "cfd_ancf_viv_fresh_openfoam_library_build_v1",
        "project_root": str(root), "runtime": str(runtime), "results": str(results),
        "source_tree": str(source_tree), "staged_source": str(staged_source),
        "output": str(output), "source_files": files,
        "source_file_count": len(files), "legacy_reuse_allowed": False,
        "authorization_required": True, "launch_performed": False,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "planned_command_shape": ["wsl.exe", "-d", "<authorized-distro>", "bash", "-lc", "wmake libso"],
    }
    manifest = results / "fresh_library_build_plan.json"
    manifest.write_bytes(_canonical(plan))
    return plan


def require_build_authorization(*, execute: bool, authorization: str | None) -> None:
    """Require the exact project token before any future external build."""
    if not execute:
        return
    if authorization != REAL_AUTHORIZATION_TOKEN:
        raise ContractError("explicit OpenFOAM/WSL/CFD authorization is required for library build")


def validate_build_output(*, runtime: Path, output: Path) -> dict[str, Any]:
    runtime, output = Path(runtime).resolve(), Path(output).resolve()
    if not _under(output, runtime):
        raise LibraryBuildError("library output escaped the fresh runtime")
    if not output.is_file() or output.suffix.lower() != ".so":
        raise LibraryBuildError("fresh deployable .so is missing")
    raw = output.read_bytes()
    if raw[:4] != b"\x7fELF":
        raise LibraryBuildError("fresh library is not an ELF shared object")
    return {"path": str(output), "size_bytes": len(raw), "sha256": _sha256(output),
            "elf_magic": True, "runtime": str(runtime), "legacy_reuse_allowed": False}


__all__ = ["LibraryBuildError", "prepare_fresh_library_build",
           "require_build_authorization", "validate_build_output"]
