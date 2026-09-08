#!/usr/bin/env bash
# Source this file before building or running the OF10-owned prototype.
# It deliberately excludes the user's legacy OpenFOAM library directory so
# every OpenFOAM soname resolves from the isolated prototype prefix.
# OF10's stock bashrc probes shell-specific variables and has harmless
# non-zero shell-customization probes. Do not enable strict mode until it has
# completed unchanged.
# The stock OF10 bashrc reads optional shell variables (for example
# ZSH_NAME).  Disable both errexit and nounset while sourcing it unchanged;
# strict mode is restored immediately afterwards.
set +e +u

if [[ $# -ne 1 ]]; then
    echo "usage: source prototype_env.sh <prototype-root>" >&2
    return 2 2>/dev/null || exit 2
fi

prototype_root=$1
of_root="$prototype_root/openfoam10"
[[ -f "$of_root/etc/bashrc" ]] || {
    echo "missing isolated OF10 bashrc: $of_root/etc/bashrc" >&2
    return 2 2>/dev/null || exit 2
}

source "$of_root/etc/bashrc"
set -euo pipefail

# Do not retain FOAM_USER_LIBBIN or the original /opt/OpenFOAM prefix.  System
# MPI and preCICE locations remain explicitly listed for their independent ABI.
export LD_LIBRARY_PATH="$FOAM_LIBBIN:$FOAM_EXT_LIBBIN:$FOAM_LIBBIN/openmpi-system:$FOAM_EXT_LIBBIN/openmpi-system:/usr/lib/x86_64-linux-gnu/openmpi/lib:/usr/local/lib:/usr/lib/x86_64-linux-gnu"

case ":$LD_LIBRARY_PATH:" in
    *":/opt/openfoam10/"*|*":/home/machao/OpenFOAM/machao-10/"*)
        echo "legacy OpenFOAM path leaked into prototype environment" >&2
        return 1 2>/dev/null || exit 1
        ;;
esac
