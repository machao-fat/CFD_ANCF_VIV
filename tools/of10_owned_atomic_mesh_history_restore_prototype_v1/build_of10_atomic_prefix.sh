#!/usr/bin/env bash
set -eo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 <prototype-root>" >&2
    exit 2
fi

prototype_root=$1
of_root="$prototype_root/openfoam10"
[[ -f "$of_root/etc/bashrc" ]] || exit 2
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prototype_env.sh" "$prototype_root"

printf 'WM_PROJECT_DIR=%s\nFOAM_LIBBIN=%s\nWM_OPTIONS=%s\n' \
    "$WM_PROJECT_DIR" "$FOAM_LIBBIN" "$WM_OPTIONS" \
    > "$prototype_root/build-environment.txt"

cd "$WM_PROJECT_DIR/src/OpenFOAM"
wmake libso > "$prototype_root/build-libOpenFOAM.log" 2>&1

cd "$WM_PROJECT_DIR/src/finiteVolume"
wmake libso > "$prototype_root/build-libfiniteVolume.log" 2>&1

# The motion solver and mover are loaded dynamically by the prototype case;
# rebuild them against this same prefix before compiling the adapter/solver.
cd "$WM_PROJECT_DIR/src/fvMotionSolver"
wmake libso > "$prototype_root/build-libfvMotionSolver.log" 2>&1
cd "$WM_PROJECT_DIR/src/fvMeshMovers"
wmake libso > "$prototype_root/build-libfvMeshMovers.log" 2>&1

cd "$WM_PROJECT_DIR/applications/solvers/incompressible/pimpleFoam"
wmake > "$prototype_root/build-pimpleFoam.log" 2>&1

sha256sum \
    "$FOAM_LIBBIN/libOpenFOAM.so" \
    "$FOAM_LIBBIN/libfiniteVolume.so" \
    "$FOAM_LIBBIN/libfvMotionSolvers.so" \
    "$FOAM_LIBBIN/libfvMeshMovers.so" \
    "$FOAM_APPBIN/pimpleFoam" \
    > "$prototype_root/of10-artifacts.sha256"

ldd -r "$FOAM_APPBIN/pimpleFoam" > "$prototype_root/pimpleFoam-ldd-r.log"
if grep -Eq 'not found|undefined symbol' "$prototype_root/pimpleFoam-ldd-r.log"; then
    exit 1
fi
