from __future__ import annotations

import os
import re
import hashlib
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from coupling.multi_slice_real_campaign.campaign import OpenFOAMSliceProcess, _wsl_path, validate_bridge_ack
from coupling.multi_slice_driver.real_process import RealProcessFreshnessError


class PersistentOpenFOAMError(RuntimeError):
    """Persistent OpenFOAM lifecycle or identity failure."""


def persistent_ready_timeout(runtime_timeout_s: float) -> float:
    """Return a bounded wait for the next motion in a persistent segment.

    The legacy 30 s value assumes one-shot OpenFOAM launches.  A persistent
    process must remain alive while the coordinator completes the preceding
    MATLAB/checkpoint barrier, which can legitimately exceed that value for
    the sequential O-only ablation.  This is only a lifecycle timeout; it
    does not relax any identity or numerical validation.
    """
    value = float(runtime_timeout_s)
    if not value > 0.0:
        raise PersistentOpenFOAMError("runtime timeout must be positive")
    return max(30.0, min(600.0, 4.0 * value))


class PersistentOpenFOAMSliceProcess(OpenFOAMSliceProcess):
    """One WSL/pimpleFoam process for one slice and one segment.

    The existing bridge, force parser and checkpoint code remain authoritative.
    This subclass only changes process lifetime and waits for the segment's
    final end time before closeout.
    """

    def __init__(self, *args: Any, segment_end_time_s: float, poll_interval_s: float = 0.02,
                 disable_force_coeffs: bool = False, cache_gamg_agglomeration: bool = False,
                 wsl_native_case_staging: bool = False, native_checkpoint_direct: bool = False,
                 compact_force_snapshot: bool = False,
                 field_write_format: str = "ascii",
                 field_write_precision: int = 16,
                 direct_wsl_exec: bool = False,
                 prewarm_openfoam_startup: bool = False,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.segment_end_time_s = float(segment_end_time_s)
        self.start_count = 0
        self._persistent_started = False
        self._closed = False
        self._seed_snapshot = None
        self._persistent_force_time_s = float(self.current_time_s)
        self.poll_interval_s = max(0.001, float(poll_interval_s))
        self.disable_force_coeffs = bool(disable_force_coeffs)
        self.cache_gamg_agglomeration = bool(cache_gamg_agglomeration)
        self.wsl_native_case_staging = bool(wsl_native_case_staging)
        self.native_checkpoint_direct = bool(native_checkpoint_direct)
        self.compact_force_snapshot = bool(compact_force_snapshot)
        if str(field_write_format) not in {"ascii", "binary"}:
            raise PersistentOpenFOAMError("field_write_format must be ascii or binary")
        self.field_write_format = str(field_write_format)
        if isinstance(field_write_precision, bool) or not (8 <= int(field_write_precision) <= 17):
            raise PersistentOpenFOAMError("field_write_precision must be an integer in [8, 17]")
        self.field_write_precision = int(field_write_precision)
        self.direct_wsl_exec = bool(direct_wsl_exec)
        self.prewarm_openfoam_startup = bool(prewarm_openfoam_startup)
        self._log_stream = None
        self._checkpoint_root_callback = None
        self._audit_case = self.case
        self._native_wsl_case: str | None = None
        self._native_stage_created = False
        self._native_archive_complete = False
        self._native_checkpoint_paths: list[Path] = []
        self.native_staging_audit: dict[str, Any] = {
            "enabled": self.wsl_native_case_staging,
            "state": "not_requested" if not self.wsl_native_case_staging else "pending",
            "audit_case": str(self._audit_case),
            "native_checkpoint_direct": self.native_checkpoint_direct,
            "checkpoint_sync_mode": "native_direct" if self.native_checkpoint_direct else "per_file_unc_copy",
            "checkpoint_syncs": [],
        }

    def _write_force_snapshot(self, source: Path, destination: Path, force: Any) -> None:
        """Write a bounded immutable snapshot of the already validated row.

        The legacy path copies the complete append-only forces.dat.  V3 may
        request only the uniquely matched row; the formal artifact manifest,
        force parser, hash and mtime checks still operate on the resulting
        immutable file.  No solver output is modified.
        """
        if not self.compact_force_snapshot:
            shutil.copyfile(source, destination)
            return
        try:
            lines = source.read_text(encoding="utf-8", errors="strict").splitlines()
        except (OSError, UnicodeError) as exc:
            raise PersistentOpenFOAMError(f"force snapshot source unreadable: {source}") from exc
        matches: list[str] = []
        for line in lines:
            fields = line.strip().split(None, 1)
            if not fields:
                continue
            try:
                candidate_time = float(fields[0])
            except ValueError:
                continue
            if abs(candidate_time - float(force.time_s)) <= 1.0e-12 * max(1.0, abs(float(force.time_s))):
                matches.append(line)
        if len(matches) != 1:
            raise PersistentOpenFOAMError(
                f"force snapshot row is not unique at time {force.time_s}: {len(matches)}"
            )
        with destination.open("w", encoding="utf-8", newline="") as stream:
            stream.write(matches[0].rstrip("\r\n") + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def set_checkpoint_root_callback(self, callback: Any) -> None:
        """Bind the scheduler's verification root without changing its API."""
        self._checkpoint_root_callback = callback

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _run_wsl_script(self, script: str, *, timeout_s: float) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=float(timeout_s), check=False,
        )

    def _native_stage_path(self) -> str:
        safe_run = re.sub(r"[^A-Za-z0-9_.-]", "_", self.run_id)
        return f"/tmp/cfd_ancf_viv_stage96/{safe_run}/slice_{self.slice_id:04d}"

    @staticmethod
    def _unc_from_wsl(path: str) -> Path:
        if not path.startswith("/"):
            raise PersistentOpenFOAMError("native WSL case path must be absolute")
        return Path(r"\\wsl.localhost\Ubuntu-22.04" + path.replace("/", "\\"))

    def _stage_native_case(self) -> None:
        if not self.wsl_native_case_staging or self._native_stage_created:
            return
        source = _wsl_path(self._audit_case)
        target = self._native_stage_path()
        parent = target.rsplit("/", 1)[0]
        prefix = "/tmp/cfd_ancf_viv_stage96/"
        if not target.startswith(prefix) or target == prefix:
            raise PersistentOpenFOAMError("native staging target is outside owned scratch root")
        script = (
            "set -eu; "
            f"test -d {shlex.quote(source)}; "
            f"rm -rf {shlex.quote(target)}; "
            f"mkdir -p {shlex.quote(parent)}; "
            f"cp -a {shlex.quote(source + '/.')} {shlex.quote(target + '/')}"
        )
        started_ns = time.time_ns()
        try:
            completed = self._run_wsl_script(script, timeout_s=max(60.0, self.runtime_config.timeout_s))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PersistentOpenFOAMError(f"native WSL staging launch failed: {exc}") from exc
        if completed.returncode != 0:
            raise PersistentOpenFOAMError(f"native WSL staging failed: {completed.stderr.strip() or completed.stdout.strip()}")
        native_case = self._unc_from_wsl(target)
        if not (native_case / "system" / "controlDict").is_file():
            raise PersistentOpenFOAMError("native WSL staging did not produce a readable case")
        self.case = native_case
        self.case_root = native_case.parent
        self._native_wsl_case = target
        self._native_stage_created = True
        self.native_staging_audit.update({
            "state": "staged",
            "native_wsl_case": target,
            "native_unc_case": str(native_case),
            "staging_started_ns": started_ns,
            "staging_completed_ns": time.time_ns(),
        })

    def _archive_native_case(self) -> None:
        if not self._native_stage_created or self._native_archive_complete:
            return
        if self._native_wsl_case is None:
            raise PersistentOpenFOAMError("native staging state is incomplete")
        started_ns = time.time_ns()
        if self.native_checkpoint_direct:
            # The native case is the authoritative read-only checkpoint source
            # during the segment.  One recursive, restartable-free copy at
            # closeout avoids 120 individual UNC file copies while retaining
            # every field in the D-drive evidence tree.
            self._audit_case.mkdir(parents=True, exist_ok=True)
            command = ["robocopy", str(self.case), str(self._audit_case), "/E", "/COPY:DAT",
                       "/DCOPY:DAT", "/R:0", "/W:0", "/J", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"]
            try:
                completed = subprocess.run(command, capture_output=True, text=True,
                                           encoding="utf-8", errors="replace", timeout=max(60.0, self.runtime_config.timeout_s),
                                           check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PersistentOpenFOAMError(f"native archive command failed: {exc}") from exc
            if completed.returncode > 7:
                raise PersistentOpenFOAMError(
                    f"native archive copy failed ({completed.returncode}): "
                    f"{completed.stderr.strip() or completed.stdout.strip()}"
                )
            self.native_staging_audit.update({
                "archive_command": command,
                "archive_return_code": int(completed.returncode),
                "archive_stdout": completed.stdout[-2000:],
                "archive_stderr": completed.stderr[-2000:],
            })
        else:
            try:
                for relative in (Path("system/controlDict"), Path("system/fvSolution"), Path("constant/dynamicMeshDict")):
                    source_file = self.case / relative
                    destination_file = self._audit_case / relative
                    if not source_file.is_file():
                        raise PersistentOpenFOAMError(f"native archive source is missing: {relative}")
                    destination_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_file, destination_file)
                    if self._sha256(source_file) != self._sha256(destination_file):
                        raise PersistentOpenFOAMError(f"native archive hash mismatch: {relative}")
                native_post = self.case / "postProcessing"
                if native_post.is_dir():
                    shutil.copytree(native_post, self._audit_case / "postProcessing", dirs_exist_ok=True, copy_function=shutil.copy2)
                for native_log in [Path(item) for item in self.log_paths]:
                    if not native_log.is_file():
                        raise PersistentOpenFOAMError(f"native archive log is missing: {native_log.name}")
                    archive_log = self._audit_case / native_log.name
                    shutil.copy2(native_log, archive_log)
                    if self._sha256(native_log) != self._sha256(archive_log):
                        raise PersistentOpenFOAMError(f"native archive log hash mismatch: {native_log.name}")
            except OSError as exc:
                raise PersistentOpenFOAMError(f"native archive copy failed: {exc}") from exc
        for native_path in self._native_checkpoint_paths:
            relative = native_path.relative_to(self.case)
            archived = self._audit_case / relative
            if (not archived.is_file() or archived.stat().st_size != native_path.stat().st_size
                    or self._sha256(archived) != self._sha256(native_path)):
                raise PersistentOpenFOAMError(f"native checkpoint archive mismatch: {relative}")
        if self._checkpoint_root_callback is not None:
            self._checkpoint_root_callback(self._audit_case.parent)
        self._native_archive_complete = True
        self.native_staging_audit.update({"state": "archived", "archive_started_ns": started_ns,
                                          "archive_completed_ns": time.time_ns()})

    def _sync_native_checkpoint(self, files: Mapping[str, Any]) -> dict[str, Any]:
        """Copy the exact completed step fields to D before formal commit.

        A WSL native filesystem can expose a freshly written file to its
        Windows UNC provider slightly later than the OpenFOAM force output.
        The global barrier is already satisfied at this point; copying and
        hashing inside WSL gives the formal D-drive checkpoint a coherent,
        immediately readable snapshot without weakening any check.
        """
        if not self._native_stage_created or self._native_wsl_case is None:
            raise PersistentOpenFOAMError("native checkpoint sync requires an active staged case")
        native_paths = list(files["static_files"].values()) + list(files["time_files"].values())
        relatives = [path.relative_to(self.case).as_posix() for path in native_paths]
        if len(relatives) != len(set(relatives)):
            raise PersistentOpenFOAMError("native checkpoint contains duplicate relative paths")
        # Do not launch a helper WSL process per slice/step.  In direct mode
        # the native files remain the immutable source for the checkpoint
        # manager; the complete case is archived once at segment closeout.
        # The metadata/hash audit is still performed before commit.
        deadline = time.monotonic() + min(5.0, max(1.0, self.runtime_config.timeout_s))
        stable: dict[Path, tuple[int, int]] = {}
        while time.monotonic() < deadline:
            current: dict[Path, tuple[int, int]] = {}
            try:
                for native_path in native_paths:
                    stat = native_path.stat()
                    current[native_path] = (int(stat.st_size), int(stat.st_mtime_ns))
            except OSError:
                current = {}
            if current and current == stable:
                break
            stable = current
            time.sleep(0.005)
        else:
            missing = [relative for path, relative in zip(native_paths, relatives) if path not in stable]
            raise PersistentOpenFOAMError(f"native checkpoint UNC visibility timeout: {missing}")
        if self.native_checkpoint_direct:
            if self._checkpoint_root_callback is not None:
                self._checkpoint_root_callback(self.case_root)
            source_hashes = {str(path.relative_to(self.case)): self._sha256(path) for path in native_paths}
            self.native_staging_audit["checkpoint_syncs"].append({
                "mode": "native_direct", "files": len(native_paths),
                "relative_paths": sorted(source_hashes), "sha256": source_hashes,
            })
            self._native_checkpoint_paths.extend(native_paths)
            return {"openfoam_time_name": files["openfoam_time_name"], "case_relative_path": files["case_relative_path"],
                    "static_files": dict(files["static_files"]), "time_files": dict(files["time_files"])}
        for native_path in native_paths:
            relative = native_path.relative_to(self.case)
            destination_path = self._audit_case / relative
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(native_path, destination_path)
            except OSError as exc:
                raise PersistentOpenFOAMError(f"native checkpoint copy failed: {relative}: {exc}") from exc
            if (destination_path.stat().st_size != native_path.stat().st_size
                    or self._sha256(destination_path) != self._sha256(native_path)):
                raise PersistentOpenFOAMError(f"native checkpoint copy hash mismatch: {relative}")
        self._native_checkpoint_paths.extend(native_paths)
        archived_static = {key: self._audit_case / value.relative_to(self.case) for key, value in files["static_files"].items()}
        archived_time = {key: self._audit_case / value.relative_to(self.case) for key, value in files["time_files"].items()}
        return {"openfoam_time_name": files["openfoam_time_name"], "case_relative_path": files["case_relative_path"],
                "static_files": archived_static, "time_files": archived_time}

    def _cleanup_native_case(self) -> None:
        if not self._native_stage_created or self._native_wsl_case is None:
            return
        target = self._native_wsl_case
        prefix = "/tmp/cfd_ancf_viv_stage96/"
        if not target.startswith(prefix) or target == prefix:
            raise PersistentOpenFOAMError("native cleanup target is outside owned scratch root")
        script = f"set -eu; rm -rf {shlex.quote(target)}; test ! -e {shlex.quote(target)}"
        completed = self._run_wsl_script(script, timeout_s=30.0)
        if completed.returncode != 0:
            raise PersistentOpenFOAMError(f"native WSL cleanup failed: {completed.stderr.strip() or completed.stdout.strip()}")
        self.native_staging_audit.update({"state": "cleaned", "cleanup_completed_ns": time.time_ns()})

    def _launch_once(self, target_time_s: float) -> None:
        if self._persistent_started:
            return
        if self.pending_seed is None:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: missing current-time seed")
        self._stage_native_case()
        self._rewrite_control_dict(target_time_s=self.segment_end_time_s, latest=self.current_clock_step > 0)
        self._rewrite_field_write_format()
        self._rewrite_field_write_precision()
        if self.disable_force_coeffs:
            self._remove_force_coeffs_function()
        if self.cache_gamg_agglomeration:
            self._enable_gamg_agglomeration_cache()
        self._rewrite_motion_timeout()
        # Publish the current-time seed before pimpleFoam constructs the
        # motion function. Starting the solver first creates a visibility
        # race in the legacy reader's initial snapshot/ack handshake.
        old_seed_ack = self.case / "coupling" / "consumed" / f"motion_consumed_{self.current_clock_step}.json"
        old_seed_ack.unlink(missing_ok=True)
        from coupling.multi_slice_real_campaign import campaign as campaign_module
        self._seed_snapshot = campaign_module.materialize_legacy_motion_bridge(
            record=self.pending_seed, case=self.case, exchange_dir="coupling", seed=True,
            seed_time_s=self.current_time_s, bridge_step_offset=1,
            seed_step_offset=self.current_clock_step,
        )
        wcase = _wsl_path(self.case); wlib = _wsl_path(self.library.parent)
        log_path = self.case / f"log.pimpleFoam_{self.run_id}_slice_{self.slice_id:04d}_persistent"
        library_path_base = (f"{wlib}:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib:"
                             "/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/dummy:"
                             "/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/openmpi-system")
        if self.direct_wsl_exec:
            command = ["wsl.exe", "-d", "Ubuntu-22.04", "--cd", wcase,
                       "env", "WM_PROJECT_DIR=/opt/openfoam10",
                       "WM_PROJECT_VERSION=10", "FOAM_ETC=/opt/openfoam10/etc",
                       "FOAM_APPBIN=/opt/openfoam10/platforms/linux64GccDPInt32Opt/bin",
                       "FOAM_LIBBIN=/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib",
                       f"LD_LIBRARY_PATH={library_path_base}",
                       "/opt/openfoam10/platforms/linux64GccDPInt32Opt/bin/pimpleFoam"]
            self._log_stream = log_path.open("w", encoding="utf-8")
            launch_kwargs = {"stdout": self._log_stream, "stderr": subprocess.STDOUT}
        else:
            shell_command = (
                "source /opt/openfoam10/etc/bashrc; "
                f"export LD_LIBRARY_PATH={library_path_base}:$LD_LIBRARY_PATH; "
                f"cd '{wcase}'; pimpleFoam > '{log_path.name}' 2>&1"
            )
            command = ["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", shell_command]
            launch_kwargs = {}
        self.process_start_ns = time.time_ns()
        self.process = subprocess.Popen(command, **launch_kwargs)
        # Intermediate global-barrier audits must read the live native log.
        # ``stop`` switches this to the D-drive archived copy only after the
        # solver has reached End and the archive hash checks have completed.
        self.start_count += 1; self._persistent_started = True; self.log_paths.append(str(log_path))

    def _rewrite_motion_timeout(self) -> None:
        """Increase only the bridge wait bound for this owned persistent case."""
        path = self.case / "constant" / "dynamicMeshDict"
        if not path.is_file():
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: dynamicMeshDict is missing")
        text = path.read_text(encoding="utf-8")
        timeout = persistent_ready_timeout(self.runtime_config.timeout_s)
        updated, count = re.subn(r"(^\s*readyTimeout\s+)[^;]+;", rf"\g<1>{format(timeout, '.12g')};", text, count=1, flags=re.MULTILINE)
        if count != 1:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: readyTimeout entry is missing")
        path.write_text(updated, encoding="utf-8")

    def _rewrite_field_write_format(self) -> None:
        """Select only the OpenFOAM field serialization representation."""
        path = self.case / "system" / "controlDict"
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(
            r"(^\s*writeFormat\s+)(?:ascii|binary)(\s*;)",
            rf"\g<1>{self.field_write_format}\g<2>", text,
            count=1, flags=re.MULTILINE,
        )
        if count != 1:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: writeFormat entry is missing")
        path.write_text(updated, encoding="utf-8")

    def _rewrite_field_write_precision(self) -> None:
        """Tune only field serialization precision; solver tolerances remain unchanged."""
        path = self.case / "system" / "controlDict"
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(
            r"(^\s*writePrecision\s+)[0-9]+(\s*;)",
            rf"\g<1>{self.field_write_precision}\g<2>", text,
            count=1, flags=re.MULTILINE,
        )
        if count != 1:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: writePrecision entry is missing")
        path.write_text(updated, encoding="utf-8")

    def _remove_force_coeffs_function(self) -> None:
        """Remove only the optional forceCoeffs diagnostic output block."""
        path = self.case / "system" / "controlDict"
        text = path.read_text(encoding="utf-8")
        marker = "cylinderForceCoeffs"
        start = text.find(marker)
        if start < 0:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: forceCoeffs block is missing")
        brace = text.find("{", start)
        if brace < 0:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: forceCoeffs block has no opening brace")
        depth = 0; end = None
        for index in range(brace, len(text)):
            if text[index] == "{": depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1; break
        if end is None:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: forceCoeffs block is unbalanced")
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", end)
        if line_end < 0: line_end = len(text)
        path.write_text(text[:line_start] + text[line_end:], encoding="utf-8")

    def _enable_gamg_agglomeration_cache(self) -> None:
        """Enable GAMG hierarchy reuse without changing solver tolerances."""
        path = self.case / "system" / "fvSolution"
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(r"(cacheAgglomeration\s+)(?:yes|no)(\s*;)", r"\1yes\2", text)
        # The bounded case template has one explicit cache setting on the
        # primary pressure GAMG solver.  Derived entries (for example pcorr)
        # may inherit or omit this optional setting, so requiring two matches
        # incorrectly rejects an otherwise valid case before solver launch.
        if count < 1:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: expected a GAMG cacheAgglomeration entry")
        path.write_text(updated, encoding="utf-8")

    def _consume_seed(self) -> None:
        if self.pending_seed is None:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: missing seed")
        snapshot = self._seed_snapshot
        if snapshot is None:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: seed was not published before launch")
        ack = self.case / "coupling" / "consumed" / f"motion_consumed_{snapshot.bridge_step}.json"
        deadline = time.monotonic() + self.runtime_config.timeout_s
        while time.monotonic() < deadline and not ack.is_file():
            if self.process is not None and self.process.poll() not in (None, 0):
                raise PersistentOpenFOAMError(f"slice {self.slice_id} exited during seed: {self.process.returncode}")
            time.sleep(self.poll_interval_s)
        if not ack.is_file(): raise PersistentOpenFOAMError(f"slice {self.slice_id} seed consumed timeout")
        validate_bridge_ack(ack_path=ack, snapshot=snapshot, record=self.pending_seed, published_ns=snapshot.published_ns)
        self.bridge_publications.append({"kind": "seed", "global_step": self.pending_seed_step, "global_time_s": float(self.pending_seed["time_s"]),
                                         "bridge_step": snapshot.bridge_step, "bridge_time_s": snapshot.bridge_time_s, "published_ns": snapshot.published_ns})

    def _start_solver(self, target_time_s: float) -> None:
        first_start = not self._persistent_started
        self._launch_once(target_time_s)
        if first_start:
            self._consume_seed()

    def prewarm_current_seed(self, *, target_time_s: float) -> None:
        """Start once from the validated source-time seed before step 1.

        This is a lifecycle-only optimization.  The seed is the accepted
        source checkpoint state; target-time motion is still published by the
        scheduler after MATLAB prediction and the normal global barrier.
        """
        if not self.prewarm_openfoam_startup:
            return
        if self._persistent_started:
            return
        self._start_solver(float(target_time_s))

    def advance_one_step(self, step: int, time_s: float) -> None:
        if not self._persistent_started or self.process is None:
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: persistent process not running")
        if self.process.poll() not in (None, 0):
            raise PersistentOpenFOAMError(f"slice {self.slice_id}: process returned {self.process.returncode}")

    def _force_path(self, time_s: float) -> Path:
        # forces.dat is append-only under the solver's original start-time
        # directory for a persistent process; it does not move with the
        # current coupling clock on each target step.
        return self.case / "postProcessing" / "cylinderForces" / format(self._persistent_force_time_s, ".12g") / "forces.dat"

    def finish_step(self, step: int, time_s: float) -> None:
        if self.last_force is not None:
            if self.last_force_artifact is None: raise RealProcessFreshnessError("consumed force artifact missing")
            from coupling.multi_slice_driver.real_process import force_file_audit
            audit = force_file_audit(self.last_force_artifact, expected=self.last_force)
            audit["source_path"] = str(self._force_path(time_s).resolve()); audit["artifact_kind"] = "immutable_consumed_force_snapshot"
            self.force_audits.append(audit)
        self.current_time_s = float(time_s); self.current_clock_step += 1; self.last_force_fingerprint = None
        self.last_force_artifact = None; self.pending_seed = None; self._seed_snapshot = None

    def checkpoint_files(self, step: int, time_s: float):
        files = super().checkpoint_files(step, time_s)
        if self.wsl_native_case_staging:
            return self._sync_native_checkpoint(files)
        return files

    def stop(self) -> None:
        if self._closed: return
        if self.process is not None:
            if self.process.poll() is None:
                # At the segment boundary pimpleFoam should reach endTime and
                # close normally.  Waiting here preserves the final ``End``
                # audit record.  On an early failure, terminate promptly so a
                # stale motion wait cannot hold cleanup indefinitely.
                at_segment_end = abs(self.current_time_s - self.segment_end_time_s) <= 1.0e-12 * max(1.0, abs(self.segment_end_time_s))
                if at_segment_end:
                    try:
                        self.process.wait(timeout=min(30.0, max(10.0, self.runtime_config.timeout_s)))
                    except subprocess.TimeoutExpired:
                        self.process.terminate()
                else:
                    self.process.terminate()
                try: self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait(timeout=10)
        if self.wsl_native_case_staging:
            self._archive_native_case()
            self.log_paths = [str(self._audit_case / Path(item).name) for item in self.log_paths]
            self._cleanup_native_case()
        if self._log_stream is not None:
            self._log_stream.close()
            self._log_stream = None
        self._closed = True

    def log_metrics(self) -> dict[str, Any]:
        result = super().log_metrics(); result["persistent_start_count"] = self.start_count; result["persistent_process"] = True
        result["native_staging"] = dict(self.native_staging_audit)
        return result
