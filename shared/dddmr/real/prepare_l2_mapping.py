"""Generate a separate real L2 mapping profile from the upstream Go2 YAML."""
import argparse
import math
from pathlib import Path
import yaml
from configure_dddmr import cuboid, replace_cuboids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ground-z", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.ground_z) or args.upstream.resolve() == args.output.resolve():
        parser.error("Require a finite measured ground height and a separate output")
    data = yaml.safe_load(args.upstream.read_text())
    replaced = replace_cuboids(data, cuboid(.77, .341, .44, 0., 0., args.ground_z))
    for node in data.values():
        if isinstance(node, dict) and "ros__parameters" in node:
            node["ros__parameters"]["use_sim_time"] = False
    ip = data["lego_loam_ip"]["ros__parameters"]
    ip["laser"].update(odom_type="wheel_odometry", base_ground_frame="base_footprint",
                       odom_child_frame="base_link", num_vertical_scans=96, num_horizontal_scans=360,
                       vertical_angle_bottom=-90., vertical_angle_top=90., scan_period=0.)
    # mapping_cloud already uses the real per-point times and LIO trajectory.
    # Disable the spinning-LiDAR timing model and uncompensated internal stitch.
    ip["imageProjection"].update(minimum_detection_range=.1, maximum_detection_range=20.,
                                 stitcher_num=1, distance_for_patch_between_rings=.3,
                                 patch_first_ring_to_baselink=False, ground_slope_tolerance=.2617994,
                                 ground_dz_tolerance=.05, ground_fov_bottom=-1.5707963,
                                 ground_fov_top=-.03, ground_positive_start=0.,
                                 ground_positive_stop=3.1415926, ground_negative_start=0.,
                                 ground_negative_stop=-3.1415926)
    mo = data["lego_loam_mo"]["ros__parameters"]["mapping"]
    mo.update(distance_between_key_frame=.25, angle_between_key_frame=.25,
              surrounding_keyframe_search_num=50,
              enable_loop_closure=False, broadcast_external_odom_tf=False, generate_testing_pg=False)
    data["lego_loam_map_visualization"]["ros__parameters"]["ground_voxel_size"] = .15
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(data, sort_keys=False))
    print(f"Prepared real L2 profile; {replaced} Cuboids, ground_z={args.ground_z:.6f} m")


if __name__ == "__main__":
    main()
