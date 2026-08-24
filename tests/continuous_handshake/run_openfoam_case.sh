#!/usr/bin/env bash
set -eo pipefail
source /opt/openfoam10/etc/bashrc
case_dir="$1"
cd "$case_dir"
exec pimpleFoam
