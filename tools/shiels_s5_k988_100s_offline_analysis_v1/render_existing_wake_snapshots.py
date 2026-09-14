"""Render velocity/vorticity/pressure snapshots from existing OpenFOAM fields.

Read-only utility. It parses the saved ASCII fields and mesh; it does not call
OpenFOAM utilities or advance a solver.
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(r"D:/研二文件/开题准备/CFD_ANCF_VIV")
CASE = ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_long_development_resume_v4_run_001/precice_displacementLaplacian"
OUT = ROOT / "results/shiels_s5_k988_100s_physical_response_v1"
FLOAT = r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?"
mpl.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"], "font.size": 7, "axes.spines.right": False, "axes.spines.top": False, "svg.fonttype": "none", "pdf.fonttype": 42})


def list_body(text: str):
    # Locate the first list opening after the FoamFile header. This is safe for
    # the ASCII mesh/field files used by this existing runtime.
    p = text.find("\n(")
    if p < 0:
        p = text.find("(")
    end = text.rfind(")")
    return text[p + 2:end] if p >= 0 and end > p else ""


def parse_points(path):
    body = list_body(path.read_text(encoding="utf-8", errors="replace"))
    vals = np.array([[float(a), float(b), float(c)] for a, b, c in re.findall(r"\(\s*(%s)\s+(%s)\s+(%s)\s*\)" % (FLOAT, FLOAT, FLOAT), body)], dtype=float)
    return vals


def parse_faces(path):
    body = list_body(path.read_text(encoding="utf-8", errors="replace"))
    faces = []
    for m in re.finditer(r"\d+\s*\(([^)]*)\)", body):
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
        if nums:
            faces.append(nums)
    return faces


def parse_int_list(path):
    body = list_body(path.read_text(encoding="utf-8", errors="replace"))
    return np.array([int(x) for x in re.findall(r"\d+", body)], dtype=int)


def cell_centres():
    mesh = CASE / "constant/polyMesh"
    pts = parse_points(mesh / "points")
    faces = parse_faces(mesh / "faces")
    owners = parse_int_list(mesh / "owner")
    n_cells = 16244
    sums = np.zeros((n_cells, 2)); counts = np.zeros(n_cells)
    for fi, face in enumerate(faces):
        if fi >= len(owners):
            break
        c = owners[fi]
        xy = pts[np.asarray(face), :2].mean(axis=0)
        if 0 <= c < n_cells:
            sums[c] += xy; counts[c] += 1
    if np.any(counts == 0):
        raise RuntimeError("some cell centres could not be reconstructed from existing mesh")
    return sums / counts[:, None]


def parse_field(path, vector):
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"internalField\s+nonuniform\s+List<[^>]+>\s+(\d+)\s*\(", text)
    if not m:
        raise RuntimeError(f"cannot parse internalField in {path}")
    n = int(m.group(1)); end = text.find("boundaryField", m.end()); body = text[m.end():end if end >= 0 else len(text)]
    if vector:
        vals = [[float(a), float(b), float(c)] for a, b, c in re.findall(r"\(\s*(%s)\s+(%s)\s+(%s)\s*\)" % (FLOAT, FLOAT, FLOAT), body)]
    else:
        vals = [float(x) for x in re.findall(FLOAT, body)]
    arr = np.asarray(vals, dtype=float)
    if len(arr) != n:
        raise RuntimeError(f"field count mismatch in {path}: header {n}, parsed {len(arr)}")
    return arr


def main():
    xy = cell_centres(); tree = cKDTree(xy); _, nn = tree.query(xy, k=9)
    snapshots = []
    for target in [20.0, 50.0, 80.0]:
        dirs = [d for d in CASE.iterdir() if d.is_dir()]
        dirs = [(abs(float(d.name) - target), d) for d in dirs if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", d.name)]
        _, d = min(dirs, key=lambda z: z[0])
        U = parse_field(d / "U", True)[:, :2]; p = parse_field(d / "p", False)
        # Least-squares cell-local gradients of the saved velocity field.
        dx = xy[nn[:, 1:]] - xy[:, None, :]
        ata = np.einsum("nki,nkj->nij", dx, dx)
        det = ata[:, 0, 0] * ata[:, 1, 1] - ata[:, 0, 1] * ata[:, 1, 0]
        inv = np.zeros_like(ata); good = abs(det) > 1e-14
        inv[good, 0, 0] = ata[good, 1, 1] / det[good]; inv[good, 1, 1] = ata[good, 0, 0] / det[good]
        inv[good, 0, 1] = -ata[good, 0, 1] / det[good]; inv[good, 1, 0] = -ata[good, 1, 0] / det[good]
        du = U[nn[:, 1:]] - U[:, None, :]
        atdu = np.einsum("nki,nkj->nij", dx, du)
        grad = np.einsum("nij,njk->nik", inv, atdu)
        vort = grad[:, 1, 0] - grad[:, 0, 1]
        snapshots.append((target, float(d.name), U, p, vort))
    fig, axs = plt.subplots(3, 2, figsize=(7.1, 7.4), sharex=True, sharey=True)
    for i, (target, actual, vel, p, vort) in enumerate(snapshots):
        speed = np.linalg.norm(vel, axis=1)
        vlim = np.nanpercentile(abs(vort), 98)
        plim = np.nanpercentile(p, [2, 98])
        ax = axs[i, 0]; sc = ax.scatter(xy[:, 0], xy[:, 1], c=vort, s=1.0, cmap="RdBu_r", vmin=-vlim, vmax=vlim, rasterized=True); ax.set_title(f"vorticity, t={actual:.3f} s"); ax.set_ylabel("y (m)"); fig.colorbar(sc, ax=ax, fraction=.046, pad=.02, label="1/s")
        ax = axs[i, 1]; sc = ax.scatter(xy[:, 0], xy[:, 1], c=p, s=1.0, cmap="viridis", vmin=plim[0], vmax=plim[1], rasterized=True); ax.set_title(f"pressure, t={actual:.3f} s"); fig.colorbar(sc, ax=ax, fraction=.046, pad=.02, label="Pa")
        for a in axs[i, :]:
            a.set_xlim(-3, 8); a.set_ylim(-3, 3); a.set_aspect("equal")
    for a in axs[-1, :]: a.set_xlabel("x (m)")
    fig.tight_layout(); fig.savefig(OUT / "wake_vorticity_pressure_snapshots.png", dpi=300, bbox_inches="tight"); fig.savefig(OUT / "wake_vorticity_pressure_snapshots.svg", bbox_inches="tight"); fig.savefig(OUT / "wake_vorticity_pressure_snapshots.pdf", bbox_inches="tight"); fig.savefig(OUT / "wake_vorticity_pressure_snapshots.tiff", dpi=600, bbox_inches="tight"); plt.close(fig)
    print({"status": "PASS", "snapshots": [x[1] for x in snapshots], "cells": int(len(xy))})


if __name__ == "__main__":
    main()
