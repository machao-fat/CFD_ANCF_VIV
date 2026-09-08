#!/usr/bin/env bash
# Run checkMesh against an immutable prototype fixture without touching its case.
set -euo pipefail

if [[ $# -ne 4 ]]; then
    echo "usage: $0 <prototype-root> <adapter-lib-dir> <case-dir> <log-path>" >&2
    exit 2
fi

prototype_root=$1
adapter_lib_dir=$2
case_dir=$3
log_path=$4
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

source "$script_dir/prototype_env.sh" "$prototype_root"
export LD_LIBRARY_PATH="$adapter_lib_dir:$LD_LIBRARY_PATH"

checkMesh -case "$case_dir" -time 0.105 -allTopology -allGeometry > "$log_path" 2>&1
