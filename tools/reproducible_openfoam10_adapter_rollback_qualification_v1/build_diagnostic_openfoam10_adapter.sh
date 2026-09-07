#!/usr/bin/env bash
# Build an isolated diagnostic library from the pinned reproducible baseline.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <source-archive.zip> <build-root> <openfoam-bashrc>" >&2
  exit 64
fi

archive=$1
build_root=$2
openfoam_bashrc=$3
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
base_patch="$script_dir/../reproducible_openfoam10_adapter_baseline_recovery_v1/patches/0001-respect-adapter-target-dir.patch"
diagnostic_patch="$script_dir/patches/0002-diagnostic-rollback-fingerprints.patch"
[[ -f "$archive" && -f "$base_patch" && -f "$diagnostic_patch" && -f "$openfoam_bashrc" ]]
[[ ! -e "$build_root" ]] || { echo "refusing to overwrite: $build_root" >&2; exit 65; }
mkdir -p "$build_root"
python3 - "$archive" "$build_root" <<'PY'
import pathlib, sys, zipfile
archive, destination = map(pathlib.Path, sys.argv[1:])
with zipfile.ZipFile(archive) as bundle:
    roots = {item.split('/', 1)[0] for item in bundle.namelist() if item}
    if len(roots) != 1: raise SystemExit('unexpected archive roots')
    bundle.extractall(destination)
PY
source_dir=$(find "$build_root" -mindepth 1 -maxdepth 1 -type d -print -quit)
patch -d "$source_dir" -p1 < "$base_patch"
patch -d "$source_dir" -p1 < "$diagnostic_patch"
set +e +u
source "$openfoam_bashrc"
set -e -u
export ADAPTER_TARGET_DIR="$build_root/lib"
mkdir -p "$ADAPTER_TARGET_DIR"
( cd "$source_dir" && bash ./Allwmake )
library="$ADAPTER_TARGET_DIR/libpreciceAdapterFunctionObject.so"
[[ -f "$library" ]]
ldd -r "$library" | tee "$build_root/ldd-r.log"
! grep -Eq 'not found|undefined symbol' "$build_root/ldd-r.log"
readelf -n "$library" | tee "$build_root/readelf-notes.log"
sha256sum "$archive" "$diagnostic_patch" "$library" | tee "$build_root/sha256sums.txt"
