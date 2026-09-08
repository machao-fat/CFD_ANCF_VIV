#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "usage: $0 <prototype-root> <build-root> <baseline-adapter-source>" >&2
    exit 2
fi

prototype_root=$1
build_root=$2
baseline_source=$3
of_root="$prototype_root/openfoam10"
patch_file="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/patches/0002-adapter-use-of10-owned-mesh-history-checkpoint.patch"

[[ -f "$of_root/etc/bashrc" && -d "$baseline_source" && -f "$patch_file" && ! -e "$build_root" ]] || exit 2
mkdir -p "$build_root"
cp -a "$baseline_source" "$build_root/openfoam-adapter"
patch -d "$build_root/openfoam-adapter" -p1 < "$patch_file"

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prototype_env.sh" "$prototype_root"
export ADAPTER_TARGET_DIR="$build_root/lib"
mkdir -p "$ADAPTER_TARGET_DIR"
(cd "$build_root/openfoam-adapter" && bash ./Allwmake) > "$build_root/Allwmake.log" 2>&1

library="$ADAPTER_TARGET_DIR/libpreciceAdapterFunctionObject.so"
[[ -f "$library" ]] || exit 1
ldd -r "$library" > "$build_root/ldd-r.log"
if grep -Eq 'not found|undefined symbol' "$build_root/ldd-r.log"; then
    exit 1
fi
sha256sum "$library" > "$build_root/lib.sha256"
readelf -n "$library" > "$build_root/readelf-notes.log"
readelf -d "$library" > "$build_root/readelf-dynamic.log"
