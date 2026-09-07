#!/usr/bin/env bash
# Build an independent lifecycle-repair diagnostic library.  Never replaces baseline/.003.
set -eo pipefail
if [[ $# -ne 3 ]]; then
  echo "usage: $0 <source-archive> <build-root> <openfoam-bashrc>" >&2
  exit 2
fi
archive="$1"
build_root="$2"
of_bashrc="$3"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
patch_baseline="$repo_root/tools/reproducible_openfoam10_adapter_baseline_recovery_v1/patches/0001-respect-adapter-target-dir.patch"
patch_diagnostic="$script_dir/patches/0002-diagnostic-rollback-fingerprints.patch"
patch_lifecycle="$script_dir/patches/0003-openfoam10-checkpoint-lifecycle-and-motion-timing.patch"
[[ -f "$archive" && -f "$patch_baseline" && -f "$patch_diagnostic" && -f "$patch_lifecycle" ]] || { echo "missing archive or patch" >&2; exit 2; }
[[ ! -e "$build_root" ]] || { echo "refusing to overwrite $build_root" >&2; exit 2; }
mkdir -p "$build_root"
python3 - "$archive" "$build_root" <<'PY'
import sys
import zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2])
PY
src="$(find "$build_root" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
patch -d "$src" -p1 < "$patch_baseline"
patch -d "$src" -p1 < "$patch_diagnostic"
patch -d "$src" -p1 < "$patch_lifecycle"
mkdir -p "$build_root/lib"
# Foundation's bashrc probes optional shell variables; do not impose this
# script's error policy while importing the environment.
set +e +u
source "$of_bashrc"
set -e
export ADAPTER_TARGET_DIR="$build_root/lib"
( cd "$src" && bash ./Allwmake ) > "$build_root/Allwmake.log" 2>&1
lib="$build_root/lib/libpreciceAdapterFunctionObject.so"
[[ -f "$lib" ]] || { tail -100 "$build_root/Allwmake.log" >&2; exit 1; }
ldd -r "$lib" > "$build_root/ldd-r.log"
if grep -E 'not found|undefined symbol' "$build_root/ldd-r.log"; then exit 1; fi
sha256sum "$lib" > "$build_root/lib.sha256"
readelf -n "$lib" > "$build_root/readelf-notes.log"
