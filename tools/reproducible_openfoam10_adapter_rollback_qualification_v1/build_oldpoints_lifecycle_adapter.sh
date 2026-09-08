#!/usr/bin/env bash
# REJECTED EXPERIMENT: build an isolated OF10 oldPoints rollback candidate.
# It is retained for source-level evidence only. Its one-window fixture exposed
# a V0 lifecycle failure, so it is not a production or default build path.
set -eo pipefail
if [[ $# -ne 3 ]]; then echo "usage: $0 <archive> <build-root> <openfoam-bashrc>" >&2; exit 2; fi
archive="$1"; build_root="$2"; of_bashrc="$3"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
base_patch="$repo_root/tools/reproducible_openfoam10_adapter_baseline_recovery_v1/patches/0001-respect-adapter-target-dir.patch"
diag_patch="$script_dir/patches/0002-diagnostic-rollback-fingerprints.patch"
time_patch="$script_dir/patches/0005-precice-time-layer-and-different-input-rollback.patch"
oldpoints_patch="$script_dir/patches/0006-of10-oldpoints-checkpoint-restore.patch"
[[ -f "$archive" && -f "$base_patch" && -f "$diag_patch" && -f "$time_patch" && -f "$oldpoints_patch" && ! -e "$build_root" ]] || exit 2
mkdir -p "$build_root"
python3 - "$archive" "$build_root" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z: z.extractall(sys.argv[2])
PY
source_dir=$(find "$build_root" -mindepth 1 -maxdepth 1 -type d -print -quit)
patch -d "$source_dir" -p1 < "$base_patch"
patch -d "$source_dir" -p1 < "$diag_patch"
patch -d "$source_dir" -p1 < "$time_patch"
patch -d "$source_dir" -p1 < "$oldpoints_patch"
set +e +u; source "$of_bashrc"; set -e
export ADAPTER_TARGET_DIR="$build_root/lib"; mkdir -p "$ADAPTER_TARGET_DIR"
(cd "$source_dir" && bash ./Allwmake) > "$build_root/Allwmake.log" 2>&1
library="$ADAPTER_TARGET_DIR/libpreciceAdapterFunctionObject.so"
[[ -f "$library" ]] || { tail -100 "$build_root/Allwmake.log" >&2; exit 1; }
ldd -r "$library" > "$build_root/ldd-r.log"
! grep -Eq 'not found|undefined symbol' "$build_root/ldd-r.log"
sha256sum "$library" > "$build_root/lib.sha256"
readelf -n "$library" > "$build_root/readelf-notes.log"
