from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence
import xml.etree.ElementTree as ET

from .participant import ParticipantBackend, ParticipantError


class PreciceBackendError(ParticipantError):
    pass


class PrecicePythonBackend(ParticipantBackend):
    """Small pyprecice 3.x backend; construction is side-effect free until initialize."""

    def __init__(
        self,
        participant_name: str,
        config_file: str | Path,
        mesh_name: str,
        displacement_data: str,
        force_data: str,
        vertices: Sequence[Sequence[float]],
        *,
        participant_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not participant_name or not mesh_name or not displacement_data or not force_data:
            raise PreciceBackendError("preCICE names must be non-empty")
        self.config_file = Path(config_file)
        if not self.config_file.is_file():
            raise PreciceBackendError(f"preCICE config does not exist: {self.config_file}")
        try:
            ET.parse(self.config_file)
        except (ET.ParseError, OSError) as exc:
            raise PreciceBackendError(f"invalid preCICE XML config: {self.config_file}") from exc
        if not vertices:
            raise PreciceBackendError("at least one mesh vertex is required")
        self.participant_name = participant_name
        self.mesh_name = mesh_name
        self.displacement_data = displacement_data
        self.force_data = force_data
        self.vertices = [tuple(float(v) for v in row) for row in vertices]
        if any(len(row) not in (2, 3) for row in self.vertices):
            raise PreciceBackendError("vertices must be 2D or 3D")
        self._factory = participant_factory
        self._participant: Any = None
        self.vertex_ids: Any = None
        self.max_timestep: float | None = None

    def initialize(self) -> None:
        if self._participant is not None:
            raise PreciceBackendError("preCICE backend already initialized")
        factory = self._factory
        if factory is None:
            try:
                import precice  # type: ignore
            except ImportError as exc:
                raise PreciceBackendError("pyprecice is not installed") from exc
            factory = precice.Participant
        try:
            self._participant = factory(self.participant_name, str(self.config_file), 0, 1)
            self.vertex_ids = self._participant.set_mesh_vertices(self.mesh_name, self.vertices)
            self.max_timestep = float(self._participant.initialize())
        except Exception as exc:
            self._participant = None
            raise PreciceBackendError(f"preCICE initialize failed: {exc}") from exc

    def write_displacement(self, payload: dict[str, Any]) -> None:
        participant = self._require_initialized()
        values = payload.get("displacement_m", payload.get("displacement"))
        if values is None:
            raise PreciceBackendError("payload lacks displacement_m")
        participant.write_data(self.mesh_name, self.displacement_data, self.vertex_ids, values)

    def advance(self, dt_s: float) -> None:
        participant = self._require_initialized()
        if dt_s <= 0:
            raise PreciceBackendError("advance dt must be positive")
        participant.advance(float(dt_s))

    def read_force(self) -> dict[str, Any]:
        participant = self._require_initialized()
        values = participant.read_data(self.mesh_name, self.force_data, self.vertex_ids, 0.0)
        try:
            values = values.tolist()
        except AttributeError:
            pass
        return {"force_N": values}

    def finalize(self) -> None:
        participant = self._require_initialized()
        try:
            participant.finalize()
        finally:
            self._participant = None
            self.vertex_ids = None

    def _require_initialized(self) -> Any:
        if self._participant is None or self.vertex_ids is None:
            raise PreciceBackendError("preCICE backend is not initialized")
        return self._participant
