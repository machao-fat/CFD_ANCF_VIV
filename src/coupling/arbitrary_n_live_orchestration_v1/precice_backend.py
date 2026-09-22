"""Side-effect-free-until-initialize preCICE fleet backend.

The backend owns one preCICE participant (the structural coordinator) and a
mesh/data handle for every manifest slice.  No import of pyprecice occurs at
construction time, so offline topology tests cannot accidentally initialize a
real coupling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
import xml.etree.ElementTree as ET

from .manifest import SliceManifest


class PreciceBackendError(RuntimeError):
    pass


class PreciceStructureFleetBackend:
    def __init__(self, manifest: SliceManifest, config_file: str | Path,
                 vertices_by_slice: Mapping[str, Sequence[Sequence[float]]],
                 *, participant_factory: Callable[..., Any] | None = None) -> None:
        self.manifest = manifest
        self.config_file = Path(config_file)
        if not self.config_file.is_file():
            raise PreciceBackendError(f"preCICE config does not exist: {self.config_file}")
        try:
            ET.parse(self.config_file)
        except (OSError, ET.ParseError) as exc:
            raise PreciceBackendError("invalid preCICE XML") from exc
        self.vertices_by_slice = {}
        for item in manifest.slices:
            rows = vertices_by_slice.get(item.slice_id)
            if not rows:
                raise PreciceBackendError(f"missing structure vertices for {item.slice_id}")
            self.vertices_by_slice[item.slice_id] = [tuple(float(value) for value in row) for row in rows]
        self._factory = participant_factory
        self._participant: Any = None
        self._vertex_ids: dict[str, Any] = {}

    def initialize(
        self,
        initial_motion_by_slice: Mapping[str, Sequence[Sequence[float]]] | None = None,
    ) -> None:
        """Define the structure mesh and initialize the preCICE participant.

        preCICE configurations may request an initial write (for example the
        HH06 absolute ``Displacement`` exchange).  In that case the initial
        values must be written after mesh definition but before
        ``Participant.initialize()``.  The argument is optional to preserve
        the existing backend API for configurations that do not request
        initial data; a live participant that does request it fails closed if
        no values are supplied for a slice.
        """
        if self._participant is not None:
            raise PreciceBackendError("structure participant already initialized")
        factory = self._factory
        if factory is None:
            try:
                import precice  # type: ignore
            except ImportError as exc:
                raise PreciceBackendError("pyprecice is not installed") from exc
            factory = precice.Participant
        self._participant = factory(self.manifest.structure_participant, str(self.config_file), 0, 1)
        try:
            for item in self.manifest.slices:
                self._vertex_ids[item.slice_id] = self._participant.set_mesh_vertices(
                    item.structure_mesh, self.vertices_by_slice[item.slice_id])
            requires_initial_data = getattr(self._participant, "requires_initial_data", None)
            if callable(requires_initial_data) and bool(requires_initial_data()):
                initial_values = initial_motion_by_slice or {}
                for item in self.manifest.slices:
                    if item.slice_id not in initial_values:
                        raise PreciceBackendError(
                            "preCICE requires initial data but no initial motion was supplied "
                            f"for {item.slice_id}"
                        )
                    self._participant.write_data(
                        item.structure_mesh,
                        item.motion_data,
                        self._vertex_ids[item.slice_id],
                        initial_values[item.slice_id],
                    )
            self._participant.initialize()
        except Exception:
            self._participant = None
            self._vertex_ids.clear()
            raise

    def write_motion(self, slice_id: str, values: Sequence[Sequence[float]]) -> None:
        participant = self._require()
        item = self.manifest.by_id(slice_id)
        participant.write_data(item.structure_mesh, item.motion_data, self._vertex_ids[slice_id], values)

    def read_force(self, slice_id: str) -> Any:
        participant = self._require()
        item = self.manifest.by_id(slice_id)
        values = participant.read_data(item.structure_mesh, item.force_data, self._vertex_ids[slice_id], 0.0)
        return values.tolist() if hasattr(values, "tolist") else values

    def advance(self, dt_s: float) -> None:
        if dt_s <= 0.0:
            raise PreciceBackendError("dt must be positive")
        self._require().advance(float(dt_s))

    def requires_writing_checkpoint(self) -> bool:
        participant = self._require()
        method = getattr(participant, "requires_writing_checkpoint", None)
        if method is None:
            raise PreciceBackendError("current preCICE API lacks requires_writing_checkpoint")
        return bool(method())

    def requires_reading_checkpoint(self) -> bool:
        participant = self._require()
        method = getattr(participant, "requires_reading_checkpoint", None)
        if method is None:
            raise PreciceBackendError("current preCICE API lacks requires_reading_checkpoint")
        return bool(method())

    def is_coupling_ongoing(self) -> bool:
        participant = self._require()
        method = getattr(participant, "is_coupling_ongoing", None)
        if method is None:
            raise PreciceBackendError("current preCICE API lacks is_coupling_ongoing")
        return bool(method())

    def finalize(self) -> None:
        participant = self._require()
        try:
            participant.finalize()
        finally:
            self._participant = None
            self._vertex_ids.clear()

    def _require(self) -> Any:
        if self._participant is None:
            raise PreciceBackendError("structure participant is not initialized")
        return self._participant
