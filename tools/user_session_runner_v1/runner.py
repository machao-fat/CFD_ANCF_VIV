from pathlib import Path
import sys
root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "src"))
from coupling.user_session_runner_v1.core import SessionRunner

project = root
runtime = project / "runtime" / "user_session_runner_v1"
SessionRunner(project, runtime).run()
