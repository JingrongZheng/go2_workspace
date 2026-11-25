#!/usr/bin/env python3
"""Generate DDDMR parameters from the upstream node configuration."""
import argparse
import math
from pathlib import Path

import yaml


def cuboid(length, width, height, center_x, center_y, ground_z):
    # Keep the lower face at the standing ground plane.
    return {
        front + side + level: [
            round(center_x + direction * length / 2, 6),
            round(center_y + lateral * width / 2, 6),
            round(ground_z + altitude * height, 6),
        ]
        for front, direction in (("f", 1), ("b", -1))
        for side, lateral in (("l", 1), ("r", -1))
        for level, altitude in (("b", 0), ("t", 1))
    }


def replace_cuboids(params, vertices):
    count = 0
    for key, value in params.items():
        if not isinstance(value, dict):
            continue
        if key == "cuboid" and vertices.keys() <= value.keys():
            value.update({name: point.copy() for name, point in vertices.items()})
            count += 1
        else:
            count += replace_cuboids(value, vertices)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ground-z", type=float, required=True,
                        help="Standing ground Z relative to the planner's base_link, in metres")
    parser.add_argument("--center-x", type=float, default=0.0)
    parser.add_argument("--center-y", type=float, default=0.0)
    parser.add_argument("--pose-graph-dir", default="", help="Real map path inside the localization container")
    parser.add_argument("--scale", type=float, default=1.1)
    args = parser.parse_args()
    if not all(map(math.isfinite, (args.ground_z, args.center_x, args.center_y, args.scale))) or args.scale < 1:
        parser.error("Offsets must be finite and scale must be at least 1")
    if args.upstream.resolve() == args.output.resolve():
        parser.error("Choose a separate output file")
    data = yaml.safe_load(args.upstream.read_text())
    length, width, height = (dim * args.scale for dim in (0.70, 0.31, 0.40))
    count = replace_cuboids(data, cuboid(length, width, height,
                                         args.center_x, args.center_y, args.ground_z))
    if not count:
        parser.error("The source contains no DDDMR eight-vertex Cuboid")
    for node in data.values():
        if isinstance(node, dict) and "ros__parameters" in node:
            node["ros__parameters"]["use_sim_time"] = False
    if "lego_loam_mo" in data:
        mapping = data["lego_loam_mo"]["ros__parameters"]["mapping"]
        mapping["broadcast_external_odom_tf"] = False
        mapping["generate_testing_pg"] = False
    if "map1" in data:
        data["map1"]["ros__parameters"]["pose_graph_dir"] = args.pose_graph_dir
    args.output.write_text(yaml.safe_dump(data, sort_keys=False))
    print(f"Updated {count} Cuboid blocks ({length:.3f} x {width:.3f} x {height:.3f} m)")


if __name__ == "__main__":
    main()
