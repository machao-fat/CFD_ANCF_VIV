#!/usr/bin/env bash

project_root="$(cd "$(dirname "$0")/../../../../.." && pwd)"
case_root="$project_root/cases/openfoam/fixed_cylinder"
study_root="$project_root/cases/openfoam/fixed_cylinder_study"
mesh_root="$case_root/mesh/gmsh/generated"
if [[ $# -ge 1 ]]; then
    study_root="$1"
fi

source /opt/openfoam10/etc/bashrc
set -euo pipefail

for mesh_name in coarse medium fine; do
    for dt_name in 0p0025 0p00125; do
        case_dir="$study_root/"$mesh_name"_dt"$dt_name
        mesh_file="$mesh_root/fixed_cylinder_"$mesh_name".msh"
        gmshToFoam "$mesh_file" -case "$case_dir" > "$case_dir/log.gmshToFoam" 2>&1
        changeDictionary -case "$case_dir" > "$case_dir/log.changeDictionary" 2>&1
        checkMesh -case "$case_dir" -allGeometry -allTopology -meshQuality > "$case_dir/log.checkMesh" 2>&1
    done
done

echo "Converted and checked all Gmsh study cases."
