#!/usr/bin/env bash
# Produce and apply a normal unified patch from the reviewed prototype source.
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "usage: $0 <of10-source-root> <prototype-source-patch>" >&2
    exit 2
fi

of_root=$1
source_patch=$2
[[ -d "$of_root/src/finiteVolume" && -f "$source_patch" ]] || exit 2

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

poly_old="$of_root/src/OpenFOAM/meshes/polyMesh/polyMesh.H"
poly_new="$tmp_dir/polyMesh.H"
fv_old="$of_root/src/finiteVolume/fvMesh/fvMesh.H"
fv_new="$tmp_dir/fvMesh.H"
make_old="$of_root/src/finiteVolume/Make/files"
make_new="$tmp_dir/files"
new_h="$tmp_dir/meshHistoryCheckpoint.H"
new_c="$tmp_dir/meshHistoryCheckpoint.C"
combined="$tmp_dir/combined.patch"

awk '
    { print }
    $0 == "class polyDistributionMap;" { print "class meshHistoryCheckpoint;" }
    previous == "    public primitiveMesh" && $0 == "{" {
        print "    friend class meshHistoryCheckpoint;"
        print ""
    }
    { previous = $0 }
' "$poly_old" > "$poly_new"

awk '
    { print }
    $0 == "class volMesh;" { print "class meshHistoryCheckpoint;" }
    previous == "    public data" && $0 == "{" {
        print "    friend class meshHistoryCheckpoint;"
        print ""
    }
    $0 == "            bool move();" {
        print ""
        print "            //- Capture OF10-owned mesh-motion history for a retry checkpoint."
        print "            //  Time and registered flow fields remain participant state."
        print "            autoPtr<meshHistoryCheckpoint> checkpointMeshHistory() const;"
        print ""
        print "            //- Restore a checkpoint created by checkpointMeshHistory()."
        print "            void restoreMeshHistory(const meshHistoryCheckpoint&);"
    }
    { previous = $0 }
' "$fv_old" > "$fv_new"

awk '
    { print }
    $0 == "fvMesh/fvMesh.C" { print "fvMesh/meshHistoryCheckpoint/meshHistoryCheckpoint.C" }
' "$make_old" > "$make_new"

sed -n '/^+#ifndef meshHistoryCheckpoint_H/,/^+#endif/p' "$source_patch" \
    | sed 's/^+//' > "$new_h"
sed -n '/^+#include "meshHistoryCheckpoint.H"/,$p' "$source_patch" \
    | sed 's/^+//' > "$new_c"

diff -u --label a/src/OpenFOAM/meshes/polyMesh/polyMesh.H \
        --label b/src/OpenFOAM/meshes/polyMesh/polyMesh.H "$poly_old" "$poly_new" \
    > "$combined" || true
diff -u --label a/src/finiteVolume/fvMesh/fvMesh.H \
        --label b/src/finiteVolume/fvMesh/fvMesh.H "$fv_old" "$fv_new" \
    >> "$combined" || true
diff -u --label a/src/finiteVolume/Make/files \
        --label b/src/finiteVolume/Make/files "$make_old" "$make_new" \
    >> "$combined" || true
diff -u --label /dev/null \
        --label b/src/finiteVolume/fvMesh/meshHistoryCheckpoint/meshHistoryCheckpoint.H \
        /dev/null "$new_h" >> "$combined" || true
diff -u --label /dev/null \
        --label b/src/finiteVolume/fvMesh/meshHistoryCheckpoint/meshHistoryCheckpoint.C \
        /dev/null "$new_c" >> "$combined" || true

patch --batch --dry-run -d "$of_root" -p1 < "$combined"
patch --batch -d "$of_root" -p1 < "$combined"
cp "$combined" "$of_root/of10_owned_mesh_history_checkpoint.patch"
