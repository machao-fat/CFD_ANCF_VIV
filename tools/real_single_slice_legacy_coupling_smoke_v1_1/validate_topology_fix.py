"""Offline regression for the generic preCICE mesh ownership contract."""
from __future__ import annotations

from pathlib import Path
import sys
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from coupling.arbitrary_n_live_orchestration_v1 import (  # noqa: E402
    build_slice_manifest,
    generate_precice_xml,
    inspect_precice_xml,
)


def main() -> int:
    for count in (1, 2, 3, 5):
        config = {
            "case_id": f"topology_fix_{count}",
            "length_m": 10.0,
            "coupling": {
                "mode": "LegacyPointLumped",
                "placement": "uniform_centers",
                "count": count,
                "active_start_m": 0.0,
                "active_end_m": 10.0,
                "slice_length_m": 1.0,
                "unit_span_m": 1.0,
                "force_representation": "integrated_slice_force_N",
            },
        }
        manifest = build_slice_manifest(config)
        xml = generate_precice_xml(manifest)
        root = ET.fromstring(xml)
        inspection = inspect_precice_xml(xml, manifest)
        if not inspection["parse_pass"]:
            raise AssertionError("generated XML did not pass topology inspection")
        participants = root.findall("participant")
        participant_names = [node.attrib["name"] for node in participants]
        expected_names = [manifest.structure_participant] + [
            item.fluid_participant for item in manifest.slices
        ]
        if participant_names != expected_names:
            raise AssertionError("participant names/order do not match manifest")
        if len(participant_names) != len(set(participant_names)):
            raise AssertionError("participant names are not unique")
        if participant_names.count(manifest.structure_participant) != 1:
            raise AssertionError("StructureCoordinator count is not one")
        if inspection["fluid_participant_count"] != count:
            raise AssertionError("fluid participant count mismatch")
        structure = next(node for node in participants
                         if node.attrib["name"] == manifest.structure_participant)
        if structure.findall("receive-mesh"):
            raise AssertionError("structure must not receive fluid meshes for mapped-force exchange")
        structure_writes = {
            (node.attrib["name"], node.attrib["mesh"])
            for node in structure.findall("write-data")
        }
        structure_reads = {
            (node.attrib["name"], node.attrib["mesh"])
            for node in structure.findall("read-data")
        }
        schemes = root.findall("{http://www.precice.org/schemas/coupling-scheme}parallel-explicit")
        if len(schemes) != count:
            raise AssertionError("scheme count mismatch")
        for item, scheme in zip(manifest.slices, schemes):
            fluid = next(node for node in participants
                         if node.attrib["name"] == item.fluid_participant)
            if (item.motion_data, item.structure_mesh) not in structure_writes:
                raise AssertionError("structure displacement write mesh mismatch")
            if (item.force_data, item.structure_mesh) not in structure_reads:
                raise AssertionError("structure force read mesh mismatch")
            if not any(node.attrib.get("name") == item.fluid_mesh
                       for node in fluid.findall("provide-mesh")):
                raise AssertionError("fluid mesh ownership mismatch")
            if not any(node.attrib.get("name") == item.motion_data
                       and node.attrib.get("mesh") == item.fluid_mesh
                       for node in fluid.findall("read-data")):
                raise AssertionError("fluid displacement read mesh mismatch")
            if not any(node.attrib.get("name") == item.force_data
                       and node.attrib.get("mesh") == item.fluid_mesh
                       for node in fluid.findall("write-data")):
                raise AssertionError("fluid force write mesh mismatch")
            exchanges = scheme.findall("exchange")
            motion = next(node for node in exchanges if node.attrib["data"] == item.motion_data)
            force = next(node for node in exchanges if node.attrib["data"] == item.force_data)
            if motion.attrib["mesh"] != item.structure_mesh:
                raise AssertionError("motion exchange must name structure mesh")
            if force.attrib["mesh"] != item.structure_mesh:
                raise AssertionError("force exchange must name mapped structure mesh")
            if force.attrib["from"] != item.fluid_participant or force.attrib["to"] != manifest.structure_participant:
                raise AssertionError("force exchange participant direction mismatch")
            if motion.attrib["from"] != manifest.structure_participant or motion.attrib["to"] != item.fluid_participant:
                raise AssertionError("motion exchange participant direction mismatch")
        forbidden_fixture_names = ("Fluid1", "Fluid2", "Fluid3", "Structure1", "Structure2", "Structure3")
        if any(token in xml for token in forbidden_fixture_names):
            raise AssertionError("generated XML contains historical fixed-slice fixture names")
        print(f"TOPOLOGY_FIX_REGRESSION=PASS Ns={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
