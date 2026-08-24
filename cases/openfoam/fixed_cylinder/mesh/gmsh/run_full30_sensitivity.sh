#!/usr/bin/env bash

project_root="$(cd "$(dirname "$0")/../../../../.." && pwd)"
study_root="$project_root/cases/openfoam/fixed_cylinder_study_full30"
result_root="$project_root/results/03_fixed_cylinder/sensitivity_full30"
if [[ $# -ge 1 ]]; then
    study_root="$1"
fi
if [[ $# -ge 2 ]]; then
    result_root="$2"
fi

source /opt/openfoam10/etc/bashrc
set -euo pipefail

mkdir -p "$result_root"

for case_name in coarse_dt0p0025 medium_dt0p0025 fine_dt0p0025 medium_dt0p00125; do
    case_dir="$study_root/$case_name"
    result_dir="$result_root/$case_name"

    if [[ -f "$result_dir/summary.json" ]]; then
        echo "Skipping completed case $case_name"
        continue
    fi

    foamDictionary "$case_dir/system/controlDict" -entry endTime -set 30 \
        > "$case_dir/log.study_controlDict" 2>&1
    foamDictionary "$case_dir/system/controlDict" -entry startFrom -set startTime \
        >> "$case_dir/log.study_controlDict" 2>&1
    cp -r "$case_dir/0.orig/." "$case_dir/0/"
    setFields -case "$case_dir" | tee "$case_dir/log.setFields"
    icoFoam -case "$case_dir" | tee "$case_dir/log.icoFoam"

    mkdir -p "$result_dir"
    python3 "$case_dir/scripts/postprocess_fixed_cylinder.py" \
        --case "$case_dir" \
        --result "$result_dir"
done

echo "Full 30 s sensitivity representatives completed."
