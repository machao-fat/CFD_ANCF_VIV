#!/usr/bin/env bash

project_root="$(cd "$(dirname "$0")/../../../../.." && pwd)"
study_root="$project_root/cases/openfoam/fixed_cylinder_study"
result_root="$project_root/results/03_fixed_cylinder/sensitivity"

source /opt/openfoam10/etc/bashrc
set -euo pipefail

for mesh_name in coarse medium fine; do
    for dt_name in 0p0025 0p00125; do
        case_dir="$study_root/"$mesh_name"_dt"$dt_name
        result_dir="$result_root/"$mesh_name"_dt"$dt_name

        foamDictionary "$case_dir/system/controlDict" -entry endTime -set 30 \
            > "$case_dir/log.extend_controlDict" 2>&1
        foamDictionary "$case_dir/system/controlDict" -entry startFrom -set latestTime \
            >> "$case_dir/log.extend_controlDict" 2>&1
        icoFoam -case "$case_dir" | tee -a "$case_dir/log.icoFoam"
        python3 "$case_dir/scripts/postprocess_fixed_cylinder.py" \
            --case "$case_dir" \
            --result "$result_dir"
    done
done

echo "All six study cases now reach 30 s."
