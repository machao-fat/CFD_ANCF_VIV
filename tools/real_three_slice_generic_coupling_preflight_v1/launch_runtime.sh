#!/usr/bin/env bash
# One frozen Ns=3 real generic-coupling preflight. No retry or parameter change.
set -u

RUNTIME_DIR="$1"; CASE_ROOT="$2"; MANIFEST="$3"; PRECICE_CONFIG="$4"
WORKER="$5"; REPO="$6"; PYTHON_TOOL="$7"; ADAPTER_LIB="$8"
LOG_DIR="$RUNTIME_DIR/logs"; PROCESS_TABLE="$RUNTIME_DIR/process_events.tsv"
mkdir -p "$LOG_DIR" "$(dirname "$PRECICE_CONFIG")/precice-sockets"
set +u; source /opt/openfoam10/etc/bashrc; set -u
export PYTHONPATH="$REPO/src:/mnt/d/CFD/CFD_ANCF_VIV/runtime/284_precice_single_slice_smoke_real_v1/python_deps${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$(dirname "$ADAPTER_LIB")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
printf 'event\tname\tpid\tstart\tend\texit_code\tcommand\tcwd\tstdout\tstderr\n' > "$PROCESS_TABLE"

STRUCT_OUT="$LOG_DIR/StructureCoordinator.stdout.log"; STRUCT_ERR="$LOG_DIR/StructureCoordinator.stderr.log"
STRUCT_CMD="python3 $PYTHON_TOOL/structure_participant.py --manifest $MANIFEST --config $PRECICE_CONFIG --worker $WORKER --trace $LOG_DIR/structure_trace.json --max-windows 3"
START_STRUCT="$(date --iso-8601=ns)"
python3 "$PYTHON_TOOL/structure_participant.py" --manifest "$MANIFEST" --config "$PRECICE_CONFIG" --worker "$WORKER" --trace "$LOG_DIR/structure_trace.json" --max-windows 3 >"$STRUCT_OUT" 2>"$STRUCT_ERR" &
STRUCT_PID=$!
printf 'start\tStructureCoordinator\t%s\t%s\t\t\t%s\t%s\t%s\t%s\n' "$STRUCT_PID" "$START_STRUCT" "$STRUCT_CMD" "$REPO" "$STRUCT_OUT" "$STRUCT_ERR" >> "$PROCESS_TABLE"

sleep 2
if ! kill -0 "$STRUCT_PID" 2>/dev/null; then
  END_STRUCT="$(date --iso-8601=ns)"; wait "$STRUCT_PID"; RC=$?
  printf 'end\tStructureCoordinator\t%s\t\t%s\t%s\t\t\t\t\n' "$STRUCT_PID" "$END_STRUCT" "$RC" >> "$PROCESS_TABLE"
  exit 20
fi

mapfile -t SLICE_ROWS < <(python3 - "$MANIFEST" <<'PY'
import json, sys
raw=json.load(open(sys.argv[1], encoding='utf-8'))
for row in raw['slices']:
    print(row['slice_id'] + '\t' + row['openfoam_case_id'] + '\t' + row['fluid_participant'])
PY
)
declare -a PIDS NAMES OUTS ERRS CWDS
for row in "${SLICE_ROWS[@]}"; do
  IFS=$'\t' read -r SID CASE_ID PARTICIPANT <<< "$row"
  OUT="$LOG_DIR/${PARTICIPANT}.stdout.log"; ERR="$LOG_DIR/${PARTICIPANT}.stderr.log"
  START="$(date --iso-8601=ns)"
  ( cd "$CASE_ROOT/$CASE_ID" || exit 21; exec pimpleFoam ) >"$OUT" 2>"$ERR" &
  PID=$!; PIDS+=("$PID"); NAMES+=("$PARTICIPANT"); OUTS+=("$OUT"); ERRS+=("$ERR"); CWDS+=("$CASE_ROOT/$CASE_ID")
  printf 'start\t%s\t%s\t%s\t\t\t%s\t%s\t%s\t%s\n' "$PARTICIPANT" "$PID" "$START" "pimpleFoam" "$CASE_ROOT/$CASE_ID" "$OUT" "$ERR" >> "$PROCESS_TABLE"
done

STRUCT_DONE=0; STRUCT_RC=0; FLUID_DONE=0; FLUID_FAIL=0
while [[ "$STRUCT_DONE" -eq 0 || "$FLUID_DONE" -lt "${#PIDS[@]}" ]]; do
  if [[ "$STRUCT_DONE" -eq 0 ]] && ! kill -0 "$STRUCT_PID" 2>/dev/null; then
    END="$(date --iso-8601=ns)"; wait "$STRUCT_PID"; STRUCT_RC=$?
    printf 'end\tStructureCoordinator\t%s\t\t%s\t%s\t\t\t\t\n' "$STRUCT_PID" "$END" "$STRUCT_RC" >> "$PROCESS_TABLE"; STRUCT_DONE=1
    if [[ "$STRUCT_RC" -ne 0 ]]; then for PID in "${PIDS[@]}"; do kill "$PID" 2>/dev/null || true; done; fi
  fi
  FLUID_DONE=0; FLUID_FAIL=0
  for INDEX in "${!PIDS[@]}"; do
    PID="${PIDS[$INDEX]}"
    if ! kill -0 "$PID" 2>/dev/null; then
      END="$(date --iso-8601=ns)"; wait "$PID"; RC=$?
      printf 'end\t%s\t%s\t\t%s\t%s\t\t\t\t\n' "${NAMES[$INDEX]}" "$PID" "$END" "$RC" >> "$PROCESS_TABLE"
      PIDS[$INDEX]=-1
      FLUID_DONE=$((FLUID_DONE+1)); if [[ "$RC" -ne 0 ]]; then FLUID_FAIL=1; fi
    fi
  done
  if [[ "$FLUID_FAIL" -eq 1 && "$STRUCT_DONE" -eq 0 ]]; then kill "$STRUCT_PID" 2>/dev/null || true; fi
  if [[ "$STRUCT_DONE" -eq 0 || "$FLUID_DONE" -lt "${#NAMES[@]}" ]]; then sleep 0.25; fi
done
if [[ "$STRUCT_DONE" -eq 0 ]]; then END="$(date --iso-8601=ns)"; wait "$STRUCT_PID"; STRUCT_RC=$?; printf 'end\tStructureCoordinator\t%s\t\t%s\t%s\t\t\t\t\n' "$STRUCT_PID" "$END" "$STRUCT_RC" >> "$PROCESS_TABLE"; fi
[[ "$STRUCT_RC" -eq 0 && "$FLUID_FAIL" -eq 0 ]] && exit 0
exit 22
