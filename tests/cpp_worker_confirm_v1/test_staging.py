from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from coupling.cpp_worker_confirm_v1.staging import StagingAuditError, audit_staging


class StagingAuditTests(unittest.TestCase):
    def _inputs(self, root: Path):
        source = root / "source.json"
        source.write_text(json.dumps({"status": "committed", "step": 559, "time_s": 2.2075,
                                      "time_tick": 2207500000,
                                      "structure": {"q": [0.0], "qdot": [0.0], "qddot": [0.0]}}) + "\n", encoding="utf-8")
        manifest_root = root / "baseline"
        manifest_root.mkdir()
        file = manifest_root / "one.txt"; file.write_text("baseline\n", encoding="utf-8")
        manifest = manifest_root / "manifest.json"
        manifest.write_text(json.dumps({"file_count": 1, "protected": True,
                                        "files": [{"path": "one.txt", "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                                                   "size_bytes": file.stat().st_size}]}) + "\n", encoding="utf-8")
        templates = []
        for sid in range(3):
            case = root / f"template_{sid}"; (case / "constant").mkdir(parents=True); (case / "system").mkdir()
            for rel in ("constant/dynamicMeshDict", "system/controlDict", "system/fvSolution"):
                path = case / rel
                path.write_text(("sliceId       %d;\n" % sid)
                                 if rel == "constant/dynamicMeshDict" else "dictionary\n", encoding="utf-8")
            (case / "multi_slice_case_config.json").write_text(json.dumps({
                "slice_id": sid, "s_ref_m": (8.333333333333334, 25.0, 41.666666666666664)[sid],
                "ancf": {"length_m": 50.0, "outer_diameter_m": 1.0, "inner_diameter_m": 0.9,
                         "youngs_modulus_pa": 3227125779.2218256, "top_tension_n": 2179104.0029808935},
                "cfd": {"rho_kgpm3": 1000.0, "nu_m2ps": 0.01}, "delta_t_s": 0.00125
            }) + "\n", encoding="utf-8")
            templates.append(case)
        worker = root / "worker.exe"; worker.write_bytes(b"worker")
        return source, manifest, templates, worker

    def test_staging_is_fail_closed_without_authorization_or_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, manifest, templates, worker = self._inputs(root)
            result = audit_staging(
                project_root=root, source_checkpoint=source,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                baseline_manifest=manifest,
                baseline_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                template_cases=templates, destination_cases=root / "new_cases",
                runtime=root / "runtime", results=root / "results", worker_executable=worker,
                deployable_library_candidates=[root / "missing.so"], real_authorization_present=False)
            self.assertEqual(result["status"], "do_not_pass")
            self.assertEqual(result["real_process_starts"], {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})
            self.assertFalse(result["launch_performed"])
            self.assertIn("explicit OpenFOAM/WSL/CFD authorization is absent", result["blockers"])

    def test_stale_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, manifest, templates, worker = self._inputs(root)
            destination = root / "new_cases" / "slice_0001"; destination.mkdir(parents=True)
            (destination / "stale").write_text("old\n", encoding="utf-8")
            result = audit_staging(
                project_root=root, source_checkpoint=source,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                baseline_manifest=manifest,
                baseline_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                template_cases=templates, destination_cases=root / "new_cases",
                runtime=root / "runtime", results=root / "results", worker_executable=worker,
                deployable_library_candidates=[], real_authorization_present=True)
            self.assertEqual(result["status"], "do_not_pass")
            self.assertIn("one or more new case destinations are neither fresh nor audited staged cases", result["blockers"])

    def test_source_identity_mismatch_fails_before_any_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, manifest, templates, worker = self._inputs(root)
            value = json.loads(source.read_text(encoding="utf-8")); value["step"] = 560
            source.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaises(StagingAuditError):
                audit_staging(
                    project_root=root, source_checkpoint=source,
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    baseline_manifest=manifest,
                    baseline_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                    template_cases=templates, destination_cases=root / "new_cases",
                    runtime=root / "runtime", results=root / "results", worker_executable=worker,
                    deployable_library_candidates=[], real_authorization_present=True)


if __name__ == "__main__":
    unittest.main()
