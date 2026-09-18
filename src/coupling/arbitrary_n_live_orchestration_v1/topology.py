"""Deterministic preCICE topology and OpenFOAM launch-plan generation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from .manifest import SliceManifest


PRECICE_DATA_NS = "http://www.precice.org/schemas/data"
PRECICE_M2N_NS = "http://www.precice.org/schemas/m2n"
PRECICE_COUPLING_NS = "http://www.precice.org/schemas/coupling-scheme"
PRECICE_MAPPING_NS = "http://www.precice.org/schemas/mapping"


class PreciceTopologyError(ValueError):
    """Generated topology is malformed or does not match its manifest."""


@dataclass(frozen=True)
class LaunchDescriptor:
    slice_id: str
    ordinal: int
    s_ref_m: float
    unit_span_m: float
    participant: str
    case_id: str
    working_directory: str
    template_source: str
    command: tuple[str, ...]
    log_path: str
    local_flow_config: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id, "ordinal": self.ordinal, "s_ref_m": self.s_ref_m,
            "unit_span_m": self.unit_span_m, "participant": self.participant,
            "case_id": self.case_id, "working_directory": self.working_directory,
            "template_source": self.template_source, "command": list(self.command),
            "log_path": self.log_path, "local_flow_config": self.local_flow_config,
        }


def generate_openfoam_launch_plan(
    manifest: SliceManifest,
    *,
    template_source: str | Path,
    output_root: str | Path,
    command: tuple[str, ...] = ("pimpleFoam",),
    log_directory: str | Path | None = None,
) -> tuple[LaunchDescriptor, ...]:
    """Return descriptors only; this function never creates or starts a process."""

    template = str(Path(template_source))
    root = Path(output_root)
    logs = Path(log_directory) if log_directory is not None else root / "logs"
    result = []
    for item in manifest.slices:
        workdir = root / item.openfoam_case_id
        result.append(LaunchDescriptor(
            slice_id=item.slice_id, ordinal=item.ordinal, s_ref_m=item.s_ref_m,
            unit_span_m=item.unit_span_m, participant=item.fluid_participant,
            case_id=item.openfoam_case_id, working_directory=str(workdir),
            template_source=template, command=tuple(command),
            log_path=str(logs / f"{item.slice_id}.log"),
            local_flow_config=item.local_flow_config,
        ))
    return tuple(result)


def generate_precice_xml(
    manifest: SliceManifest,
    *,
    time_window_s: float = 0.005,
    max_time_s: float = 0.2,
    exchange_directory: str = "./precice-sockets",
) -> str:
    """Generate a one-structure/N-fluid composition of bi-coupling schemes.

    preCICE's explicit multi-participant composition permits one structure
    participant to exchange with every fluid participant.  Each slice gets a
    distinct pair of meshes and a distinct scheme, while the structure
    participant and its ANCF state remain singular.
    """

    if time_window_s <= 0.0 or max_time_s <= 0.0:
        raise PreciceTopologyError("time_window_s and max_time_s must be positive")
    ET.register_namespace("data", PRECICE_DATA_NS)
    ET.register_namespace("m2n", PRECICE_M2N_NS)
    ET.register_namespace("coupling-scheme", PRECICE_COUPLING_NS)
    ET.register_namespace("mapping", PRECICE_MAPPING_NS)
    root = ET.Element("precice-configuration")
    ET.SubElement(root, f"{{{PRECICE_DATA_NS}}}vector", name="Displacement", **{"waveform-degree": "1"})
    ET.SubElement(root, f"{{{PRECICE_DATA_NS}}}vector", name="Force", **{"waveform-degree": "1"})
    for item in manifest.slices:
        structure_mesh = ET.SubElement(root, "mesh", name=item.structure_mesh, dimensions="2")
        ET.SubElement(structure_mesh, "use-data", name=item.motion_data)
        ET.SubElement(structure_mesh, "use-data", name=item.force_data)
        fluid_mesh = ET.SubElement(root, "mesh", name=item.fluid_mesh, dimensions="2")
        ET.SubElement(fluid_mesh, "use-data", name=item.motion_data)
        ET.SubElement(fluid_mesh, "use-data", name=item.force_data)
    for item in manifest.slices:
        ET.SubElement(root, f"{{{PRECICE_M2N_NS}}}sockets",
                      acceptor=manifest.structure_participant,
                      connector=item.fluid_participant,
                      **{"exchange-directory": exchange_directory})
    structure = ET.SubElement(root, "participant", name=manifest.structure_participant)
    for item in manifest.slices:
        ET.SubElement(structure, "provide-mesh", name=item.structure_mesh)
        ET.SubElement(structure, "write-data", name=item.motion_data, mesh=item.structure_mesh)
        ET.SubElement(structure, "read-data", name=item.force_data, mesh=item.structure_mesh)
    for item in manifest.slices:
        fluid = ET.SubElement(root, "participant", name=item.fluid_participant)
        ET.SubElement(fluid, "receive-mesh", name=item.structure_mesh, from_=manifest.structure_participant)
        # ElementTree cannot emit the XML attribute ``from`` through a Python
        # keyword; repair it explicitly after creation.
        fluid[-1].attrib["from"] = fluid[-1].attrib.pop("from_")
        ET.SubElement(fluid, "provide-mesh", name=item.fluid_mesh)
        ET.SubElement(fluid, f"{{{PRECICE_MAPPING_NS}}}nearest-neighbor",
                      direction="read", **{"from": item.structure_mesh, "to": item.fluid_mesh}, constraint="consistent")
        ET.SubElement(fluid, f"{{{PRECICE_MAPPING_NS}}}nearest-neighbor",
                      direction="write", **{"from": item.fluid_mesh, "to": item.structure_mesh}, constraint="conservative")
        ET.SubElement(fluid, "write-data", name=item.force_data, mesh=item.fluid_mesh)
        ET.SubElement(fluid, "read-data", name=item.motion_data, mesh=item.fluid_mesh)
    for item in manifest.slices:
        scheme = ET.SubElement(root, f"{{{PRECICE_COUPLING_NS}}}parallel-explicit")
        ET.SubElement(scheme, "participants", first=manifest.structure_participant, second=item.fluid_participant)
        ET.SubElement(scheme, "time-window-size", value=f"{float(time_window_s):.17g}")
        ET.SubElement(scheme, "max-time", value=f"{float(max_time_s):.17g}")
        ET.SubElement(scheme, "exchange", data=item.motion_data, mesh=item.structure_mesh,
                      **{"from": manifest.structure_participant, "to": item.fluid_participant})
        # Force is written on the fluid mesh and conservatively mapped to the
        # structure mesh.  The exchange declaration therefore names the
        # source (fluid) mesh, while the structure participant reads the
        # mapped data from its own mesh.
        ET.SubElement(scheme, "exchange", data=item.force_data, mesh=item.fluid_mesh,
                      **{"from": item.fluid_participant, "to": manifest.structure_participant})
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def inspect_precice_xml(xml_text: str, manifest: SliceManifest) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PreciceTopologyError("generated XML is not parseable") from exc
    participants = [node.attrib.get("name") for node in root.findall("participant")]
    expected_participants = [manifest.structure_participant] + [item.fluid_participant for item in manifest.slices]
    if participants != expected_participants:
        raise PreciceTopologyError("participant order/set does not match manifest")
    schemes = root.findall(f"{{{PRECICE_COUPLING_NS}}}parallel-explicit")
    if len(schemes) != manifest.ns:
        raise PreciceTopologyError("coupling scheme count does not equal Ns")
    scheme_pairs = []
    for scheme in schemes:
        pair = scheme.find("participants")
        if pair is None:
            raise PreciceTopologyError("scheme lacks participants")
        scheme_pairs.append((pair.attrib.get("first"), pair.attrib.get("second")))
    expected_pairs = [(manifest.structure_participant, item.fluid_participant) for item in manifest.slices]
    if scheme_pairs != expected_pairs:
        raise PreciceTopologyError("scheme participant pairs do not match manifest")
    return {
        "parse_pass": True,
        "participant_count": len(participants),
        "fluid_participant_count": manifest.ns,
        "structure_participant_count": participants.count(manifest.structure_participant),
        "coupling_scheme_count": len(schemes),
        "unique_participants": len(set(participants)) == len(participants),
        "manifest_sha256": manifest.manifest_sha256,
        "participants": participants,
        "scheme_pairs": [list(pair) for pair in scheme_pairs],
    }
