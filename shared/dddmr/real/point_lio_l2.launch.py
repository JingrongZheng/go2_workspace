"""Run the L2 front end from ROS topics supplied by a bag or a sensor source."""
import json
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, RegisterEventHandler, Shutdown
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    geometry = json.loads(Path(__file__).with_name("go2_nominal_geometry.json").read_text())
    radar = next(t for t in geometry["transforms"] if t["child"] == "radar" and t["parent"] == "base")
    lidar_in_base = radar["translation_m"]
    rotation = radar["rotation_matrix"]
    imu_in_lidar = geometry["l2_internal_imu_reference"]["t_lidar_imu_m"]
    # p_base = R * p_lidar + t. Invert the composed base <- internal IMU pose.
    imu_in_base = [t + sum(r * x for r, x in zip(row, imu_in_lidar))
                   for t, row in zip(lidar_in_base, rotation)]
    base_in_imu = [-sum(rotation[i][j] * imu_in_base[i] for i in range(3))
                   for j in range(3)]
    pitch = radar["rpy_rad"][1]
    static_identity_rotation = ["--roll", "0", "--pitch", "0", "--yaw", "0"]

    def static_tf(name, parent, child, xyz, angles):
        return Node(package="tf2_ros", executable="static_transform_publisher", name=name,
                    arguments=[item for axis, value in zip("xyz", xyz)
                               for item in (f"--{axis}", str(value))]
                    + angles + ["--frame-id", parent, "--child-frame-id", child])

    play = ExecuteProcess(
        cmd=["ros2", "bag", "play", "/recorded-bag", "--delay", "3", "--topics",
             LaunchConfiguration("cloud_topic"), LaunchConfiguration("imu_topic")],
        condition=IfCondition(LaunchConfiguration("play_bag")),
        output="screen",
    )
    return LaunchDescription([
        DeclareLaunchArgument("play_bag", default_value="false"),
        DeclareLaunchArgument("cloud_topic", description="Raw L2 PointCloud2 with per-point time"),
        DeclareLaunchArgument("imu_topic", description="Time-synchronized L2 internal IMU"),
        Node(
            package="point_lio", executable="pointlio_mapping", name="laserMapping",
            output="screen",
            parameters=[
                str(Path(get_package_share_directory("point_lio")) / "config/unilidar_l2.yaml"),
                {"use_sim_time": False,
                 "cube_side_length": 1000.0, "init_map_size": 20000,
                 "mapping.plane_thr": 0.03,
                 "common.lid_topic": LaunchConfiguration("cloud_topic"),
                 "common.imu_topic": LaunchConfiguration("imu_topic"),
                 "odom_header_frame_id": "odom", "odom_child_frame_id": "l2_imu",
                 "odometry.publish_odometry_without_downsample": False,
                 "pcd_save.pcd_save_en": False,
                 "filter_size_surf": 0.1, "filter_size_map": 0.1},
            ],
        ),
        ExecuteProcess(
            cmd=["/usr/bin/python3", str(Path(__file__).with_name("body_odometry.py")),
                 *map(str, base_in_imu), str(-pitch)],
            output="screen",
        ),
        static_tf("l2_imu_to_base", "l2_imu", "base_link", base_in_imu,
                  ["--roll", "0", "--pitch", str(-pitch), "--yaw", "0"]),
        static_tf("l2_imu_to_lidar", "l2_imu", "lidar_link",
                  [-value for value in imu_in_lidar], static_identity_rotation),
        RegisterEventHandler(OnProcessExit(target_action=play, on_exit=[Shutdown()])),
        play,
    ])
