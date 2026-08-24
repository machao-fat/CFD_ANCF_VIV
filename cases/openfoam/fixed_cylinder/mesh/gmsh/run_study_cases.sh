#!/usr/bin/env bash

project_root="$(cd "$(dirname "$0")/../../../../.." && pwd)"
study_root="$project_root/cases/openfoam/fixed_cylinder_study"
result_root="$project_root/results/03_fixed_cylinder/sensitivity"

source /opt/openfoam10/etc/bashrc
set -euo pipefail

mkdir -p "$result_root"

for mesh_name in coarse medium fine; do
    for dt_name in 0p0025 0p00125; do
        case_dir="$study_root/"$mesh_name"_dt"$dt_name
        result_dir="$result_root/"$mesh_name"_dt"$dt_name

        if [[ -f "$result_dir/summary.json" ]]; then
            echo "Skipping completed case $mesh_name/$dt_name"
            continue
        fi
        if [[ -e "$case_dir/log.icoFoam" || -d "$case_dir/postProcessing" ]]; then
            echo "Existing generated output detected in $case_dir; clean that study case before rerunning." >&2
            exit 2
        fi

        cp -r "$case_dir/0.orig/." "$case_dir/0/"
        setFields -case "$case_dir" | tee "$case_dir/log.setFields"
        icoFoam -case "$case_dir" | tee "$case_dir/log.icoFoam"

        mkdir -p "$result_dir"
        python3 "$case_dir/scripts/postprocess_fixed_cylinder.py" \
            --case "$case_dir" \
            --result "$result_dir"
    done
done

echo "All six fixed-cylinder mesh/time-step study cases completed."
