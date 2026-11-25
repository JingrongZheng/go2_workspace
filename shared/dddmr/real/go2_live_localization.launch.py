"""L2/chassis Point-LIO + DDDMR 3D MCL localization only (R3); no planner or controller."""
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    root = Path(__file__).parent
    params = LaunchConfiguration("parameters")

    return LaunchDescription([
        DeclareLaunchArgument("cloud_topic", default_value="/go2/relay/cloud"),
        DeclareLaunchArgument("imu_topic", default_value="/go2/relay/chassis_imu"),
        DeclareLaunchArgument("parameters", default_value=str(root / "config/l2_localization_lab.yaml")),
        DeclareLaunchArgument("ground_z", default_value="-0.3168676504844956"),
        DeclareLaunchArgument("accumulation_frames", default_value="3"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(root / "point_lio_chassis.launch.py")),
            launch_arguments={
                "cloud_topic": LaunchConfiguration("cloud_topic"),
                "imu_topic": LaunchConfiguration("imu_topic"),
                "play_bag": "false",
            }.items(),
        ),
        ExecuteProcess(
            cmd=[
                "/usr/bin/python3", str(root / "mapping_cloud.py"),
                "--cloud-topic", LaunchConfiguration("cloud_topic"),
                "--ground-z", LaunchConfiguration("ground_z"),
                "--frames", LaunchConfiguration("accumulation_frames"),
            ],
            output="screen",
        ),
        Node(
            package="tf2_ros",
            executable="static_transform_publisher",
            name="base_to_footprint",
            arguments=["--x", "0", "--y", "0", "--z", LaunchConfiguration("ground_z"),
                       "--roll", "0", "--pitch", "0", "--yaw", "0",
                       "--frame-id", "base_link", "--child-frame-id", "base_footprint"],
            output="screen",
        ),
        Node(
            package="lego_loam_bor",
            executable="mcl_feature",
            parameters=[params, {"use_sim_time": False}],
            remappings=[("/lslidar_point_cloud", "/dddmr/lidar_points"), ("/odom", "/odom")],
            output="screen",
        ),
        Node(
            package="dddmr_pg_map_server",
            executable="dddmr_pg_map_server_node",
            parameters=[params],
            output="screen",
        ),
        Node(
            package="mcl_3dl",
            executable="mcl_3dl",
            parameters=[params, {"use_sim_time": False}],
            output="screen",
        ),
    ])
