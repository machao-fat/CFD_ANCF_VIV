from pathlib import Path
import sys

project = Path(sys.argv[1]).resolve()
runtime = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(project / "src"))
from coupling.user_session_runner_v1.core import atomic_write_json, make_probe_contract

contract = make_probe_contract(project, runtime)
atomic_write_json(runtime / "inbox" / (contract["run_id"] + ".json"), contract)
print(contract["run_id"], contract["contract_sha256"])
