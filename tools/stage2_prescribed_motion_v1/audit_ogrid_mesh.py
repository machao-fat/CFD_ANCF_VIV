#!/usr/bin/env python3
"""Fail-closed structural audit for the Stage 2 Gmsh 2.2 O-grid mesh."""

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path


REQUIRED_PHYSICAL_GROUPS = {
    "inlet": 1,
    "outlet": 1,
    "upper": 1,
    "lower": 1,
    "cylinder": 1,
    "motionInterface": 1,
    "movingFluid": 2,
    "outerFluid": 2,
}
AREA_TOLERANCE = 1.0e-12
LENGTH_TOLERANCE = 1.0e-12


def section(lines, name):
    try:
        start = lines.index(f"${name}") + 1
        end = lines.index(f"$End{name}", start)
    except ValueError as exc:
        raise ValueError(f"missing ${name} section") from exc
    return lines[start:end]


def signed_area(points):
    twice_area = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        twice_area += x1 * y2 - x2 * y1
    return 0.5 * twice_area


def audit(mesh_path):
    lines = mesh_path.read_text(encoding="ascii").splitlines()
    physical_lines = section(lines, "PhysicalNames")
    physical_count = int(physical_lines[0])
    physical_groups = {}
    for line in physical_lines[1:]:
        dim, tag, quoted_name = line.split(maxsplit=2)
        physical_groups[quoted_name.strip('"')] = {"dimension": int(dim), "tag": int(tag)}
    if len(physical_groups) != physical_count:
        raise ValueError("physical-name count is inconsistent")

    node_lines = section(lines, "Nodes")
    node_count = int(node_lines[0])
    nodes = {}
    for line in node_lines[1:]:
        fields = line.split()
        node_id = int(fields[0])
        xyz = tuple(float(value) for value in fields[1:4])
        if not all(math.isfinite(value) for value in xyz):
            raise ValueError(f"node {node_id} is non-finite")
        nodes[node_id] = xyz
    if len(nodes) != node_count:
        raise ValueError("node count is inconsistent or node IDs are duplicated")

    element_lines = section(lines, "Elements")
    declared_element_count = int(element_lines[0])
    physical_elements = Counter()
    element_signatures = set()
    node_uses = Counter()
    cell_count = 0
    line_count = 0
    min_area = math.inf
    min_length = math.inf
    degenerate = []
    duplicate_elements = []

    for line in element_lines[1:]:
        fields = [int(value) for value in line.split()]
        element_id, element_type, tag_count = fields[:3]
        tags = fields[3:3 + tag_count]
        element_nodes = fields[3 + tag_count:]
        if not tags:
            raise ValueError(f"element {element_id} has no physical tag")
        if any(node_id not in nodes for node_id in element_nodes):
            raise ValueError(f"element {element_id} references an absent node")
        signature = (element_type, tuple(sorted(element_nodes)))
        if signature in element_signatures:
            duplicate_elements.append(element_id)
        element_signatures.add(signature)
        node_uses.update(element_nodes)
        physical_elements[tags[0]] += 1

        if element_type == 1:
            line_count += 1
            x1, y1, _ = nodes[element_nodes[0]]
            x2, y2, _ = nodes[element_nodes[1]]
            length = math.hypot(x2 - x1, y2 - y1)
            min_length = min(min_length, length)
            if length <= LENGTH_TOLERANCE:
                degenerate.append(element_id)
        elif element_type in (2, 3):
            cell_count += 1
            polygon = [(nodes[node_id][0], nodes[node_id][1]) for node_id in element_nodes]
            area = abs(signed_area(polygon))
            min_area = min(min_area, area)
            if area <= AREA_TOLERANCE:
                degenerate.append(element_id)

    if len(element_lines) - 1 != declared_element_count:
        raise ValueError("element count is inconsistent")

    missing_groups = {
        name: dimension for name, dimension in REQUIRED_PHYSICAL_GROUPS.items()
        if physical_groups.get(name, {}).get("dimension") != dimension
    }
    empty_groups = [
        name for name, group in physical_groups.items()
        if group["tag"] not in physical_elements
    ]
    physical_element_counts = {
        name: physical_elements[group["tag"]]
        for name, group in physical_groups.items()
    }
    duplicate_coordinates = []
    coordinates_seen = {}
    for node_id, coordinate in nodes.items():
        if coordinate in coordinates_seen:
            duplicate_coordinates.append((coordinates_seen[coordinate], node_id))
        coordinates_seen[coordinate] = node_id
    isolated_nodes = sorted(set(nodes) - set(node_uses))

    status = not any((missing_groups, empty_groups, duplicate_coordinates,
                      duplicate_elements, isolated_nodes, degenerate))
    return {
        "mesh": str(mesh_path),
        "pass": status,
        "physical_groups": physical_groups,
        "node_count": node_count,
        "element_count": declared_element_count,
        "line_element_count": line_count,
        "cell_count": cell_count,
        "minimum_line_length": min_length,
        "minimum_cell_area": min_area,
        "physical_element_counts": physical_element_counts,
        "missing_or_wrong_dimension_groups": missing_groups,
        "empty_physical_groups": empty_groups,
        "duplicate_coordinate_node_pairs": duplicate_coordinates,
        "duplicate_element_ids": duplicate_elements,
        "isolated_node_ids": isolated_nodes,
        "degenerate_element_ids": degenerate,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mesh", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit(args.mesh)
    except (OSError, ValueError, UnicodeError) as exc:
        report = {"mesh": str(args.mesh), "pass": False, "error": str(exc)}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not report["pass"]:
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
