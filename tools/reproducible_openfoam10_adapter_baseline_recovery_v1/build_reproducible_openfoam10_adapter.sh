#!/usr/bin/env bash
# Build an isolated OpenFOAM Foundation 10 adapter baseline from one pinned archive.
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "usage: $0 <source-archive.zip> <build-root> <openfoam-bashrc>" >&2
    exit 64
fi

archive=$1
build_root=$2
openfoam_bashrc=$3
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
patch_file="$script_dir/patches/0001-respect-adapter-target-dir.patch"

[[ -f "$archive" && -f "$patch_file" && -f "$openfoam_bashrc" ]]
[[ ! -e "$build_root" ]] || { echo "refusing to overwrite build root: $build_root" >&2; exit 65; }

mkdir -p "$build_root"
python3 - "$archive" "$build_root" <<'PY'
import pathlib
import sys
import zipfile

archive = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
with zipfile.ZipFile(archive) as bundle:
    roots = {path.split('/', 1)[0] for path in bundle.namelist() if path}
    if len(roots) != 1:
        raise SystemExit(f"unexpected archive roots: {sorted(roots)}")
    bundle.extractall(destination)
print(next(iter(roots)))
PY

source_dir=$(find "$build_root" -mindepth 1 -maxdepth 1 -type d -print -quit)
[[ -n "$source_dir" ]]
patch -d "$source_dir" -p1 < "$patch_file"

# Foundation OpenFOAM's bashrc probes optional shell variables that are unset
# under a strict POSIX-shell environment. Keep strict checking for this script
# but source the vendor environment with nounset temporarily disabled.
set +e +u
source "$openfoam_bashrc"
set -e -u
export ADAPTER_TARGET_DIR="$build_root/lib"
mkdir -p "$ADAPTER_TARGET_DIR"

(
    cd "$source_dir"
    # ZIP archives do not preserve Unix execute bits. Invoke the pinned source
    # through bash so archive format cannot silently change build behavior.
    bash ./Allwmake
)

library="$ADAPTER_TARGET_DIR/libpreciceAdapterFunctionObject.so"
[[ -f "$library" ]]
ldd -r "$library" | tee "$build_root/ldd-r.log"
if grep -Eq 'not found|undefined symbol' "$build_root/ldd-r.log"; then
    echo "dynamic-link audit failed" >&2
    exit 66
fi
readelf -d "$library" | tee "$build_root/readelf-dynamic.log"
readelf -n "$library" | tee "$build_root/readelf-notes.log"
sha256sum "$archive" "$library" | tee "$build_root/sha256sums.txt"
{
    echo "WM_PROJECT=$WM_PROJECT"
    echo "WM_PROJECT_VERSION=$WM_PROJECT_VERSION"
    echo "WM_PROJECT_DIR=$WM_PROJECT_DIR"
    echo "WM_OPTIONS=$WM_OPTIONS"
    echo "WM_CXX=$WM_CXX"
    echo "WM_CXXFLAGS=$WM_CXXFLAGS"
    echo "WM_LDFLAGS=$WM_LDFLAGS"
    echo "wmake=$(command -v wmake)"
    g++ --version | head -n 1
    echo "preCICE=$(pkg-config --modversion libprecice)"
    echo "pkg_config_libs=$(pkg-config --libs libprecice)"
    echo "LD_LIBRARY_PATH=$LD_LIBRARY_PATH"
} > "$build_root/environment-manifest.txt"
