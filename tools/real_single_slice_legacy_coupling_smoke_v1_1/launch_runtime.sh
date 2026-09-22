#!/usr/bin/env bash
# One-shot validation launcher for the V1.1 real Ns=1 smoke.
# This is validation tooling only; it must not retry or alter case/source files.
set -u

RUNTIME_DIR="$1"
CASE_DIR="$2"
MANIFEST="$3"
PRECICE_CONFIG="$4"
WORKER="$5"
REPO="$6"
PYTHON_TOOL="$7"
ADAPTER_LIB="$8"

LOG_DIR="$RUNTIME_DIR/logs"
PROCESS_TABLE="$RUNTIME_DIR/process_events.tsv"
mkdir -p "$LOG_DIR"

# OpenFOAM's bashrc reads optional shell variables that may be unset under
# nounset.  This is launcher compatibility handling only; restore nounset
# before any participant is started.
set +u
source /opt/openfoam10/etc/bashrc
set -u
export PYTHONPATH="$REPO/src:/mnt/d/CFD/CFD_ANCF_VIV/runtime/284_precice_single_slice_smoke_real_v1/python_deps${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$(dirname "$ADAPTER_LIB")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

printf 'event\tname\tpid\tstart\tend\texit_code\tcommand\tcwd\tstdout\tstderr\n' > "$PROCESS_TABLE"

structure_out="$LOG_DIR/StructureCoordinator.stdout.log"
structure_err="$LOG_DIR/StructureCoordinator.stderr.log"
fluid_out="$LOG_DIR/Fluid_slice_0000.stdout.log"
fluid_err="$LOG_DIR/Fluid_slice_0000.stderr.log"
structure_cmd="python3 $PYTHON_TOOL/structure_participant.py --manifest $MANIFEST --config $PRECICE_CONFIG --worker $WORKER --trace $LOG_DIR/structure_trace.json --max-windows 3"
fluid_cmd="pimpleFoam"

start_structure="$(date --iso-8601=ns)"
python3 "$PYTHON_TOOL/structure_participant.py" \
  --manifest "$MANIFEST" \
  --config "$PRECICE_CONFIG" \
  --worker "$WORKER" \
  --trace "$LOG_DIR/structure_trace.json" \
  --max-windows 3 \
  >"$structure_out" 2>"$structure_err" &
STRUCTURE_PID=$!
printf 'start\tStructureCoordinator\t%s\t%s\t\t\t%s\t%s\t%s\t%s\n' "$STRUCTURE_PID" "$start_structure" "$structure_cmd" "$REPO" "$structure_out" "$structure_err" >> "$PROCESS_TABLE"

sleep 2
if ! kill -0 "$STRUCTURE_PID" 2>/dev/null; then
  end_structure="$(date --iso-8601=ns)"
  wait "$STRUCTURE_PID"; structure_rc=$?
  printf 'end\tStructureCoordinator\t%s\t\t%s\t%s\t\t\t\t\n' "$STRUCTURE_PID" "$end_structure" "$structure_rc" >> "$PROCESS_TABLE"
  exit 20
fi

start_fluid="$(date --iso-8601=ns)"
(
  cd "$CASE_DIR" || exit 21
  exec pimpleFoam
) >"$fluid_out" 2>"$fluid_err" &
FLUID_PID=$!
printf 'start\tFluid_slice_0000\t%s\t%s\t\t\t%s\t%s\t%s\t%s\n' "$FLUID_PID" "$start_fluid" "$fluid_cmd" "$CASE_DIR" "$fluid_out" "$fluid_err" >> "$PROCESS_TABLE"

structure_done=0
fluid_done=0
structure_rc=0
fluid_rc=0

while [[ "$structure_done" -eq 0 || "$fluid_done" -eq 0 ]]; do
  if [[ "$structure_done" -eq 0 ]] && ! kill -0 "$STRUCTURE_PID" 2>/dev/null; then
    end_structure="$(date --iso-8601=ns)"
    wait "$STRUCTURE_PID"; structure_rc=$?
    printf 'end\tStructureCoordinator\t%s\t\t%s\t%s\t\t\t\t\n' "$STRUCTURE_PID" "$end_structure" "$structure_rc" >> "$PROCESS_TABLE"
    structure_done=1
    if [[ "$structure_rc" -ne 0 && "$fluid_done" -eq 0 ]]; then
      kill "$FLUID_PID" 2>/dev/null || true
    fi
  fi
  if [[ "$fluid_done" -eq 0 ]] && ! kill -0 "$FLUID_PID" 2>/dev/null; then
    end_fluid="$(date --iso-8601=ns)"
    wait "$FLUID_PID"; fluid_rc=$?
    printf 'end\tFluid_slice_0000\t%s\t\t%s\t%s\t\t\t\t\n' "$FLUID_PID" "$end_fluid" "$fluid_rc" >> "$PROCESS_TABLE"
    fluid_done=1
    if [[ "$fluid_rc" -ne 0 && "$structure_done" -eq 0 ]]; then
      kill "$STRUCTURE_PID" 2>/dev/null || true
    fi
  fi
  if [[ "$structure_done" -eq 0 || "$fluid_done" -eq 0 ]]; then
    sleep 0.25
  fi
done

if [[ "$structure_rc" -eq 0 && "$fluid_rc" -eq 0 ]]; then
  exit 0
fi
exit 22
