from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
if not path.exists():
    print('state=NOT_STARTED')
    raise SystemExit(0)
s = json.loads(path.read_text(encoding='utf-8'))
print('state=' + str(s.get('state', 'UNKNOWN')))
print('PID=' + str(s.get('pid')))
session = s.get('session') or {}
print('SessionId=' + str(session.get('session_id')))
print('USERNAME=' + str(session.get('username')))
print('start_time=' + str(s.get('start_time')))
contract = s.get('current_contract') or {}
print('current_contract=' + str(contract.get('contract_sha256')))
print('current_run_id=' + str(s.get('current_run_id')))
print('MATLAB_PID=' + str(s.get('matlab_pid')))
print('OpenFOAM_PID=' + str(s.get('openfoam_pid')))
print('WSL_PID=' + str(s.get('wsl_pid')))
print('last_event=' + str(s.get('last_event')))
print('last_error=' + str(s.get('last_error')))
print('residual_count=' + str(s.get('residual_count')))
print('runtime=' + str(s.get('runtime')))
