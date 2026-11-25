"""Sensor-only L2 adapter and DDDMR map builder; no planner or controller."""
from pathlib import Path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    root = Path(__file__).parent
    return LaunchDescription([
        DeclareLaunchArgument("parameters"), DeclareLaunchArgument("cloud_topic"),
        DeclareLaunchArgument("ground_z"), DeclareLaunchArgument("accumulation_frames", default_value="3"),
        ExecuteProcess(cmd=["/usr/bin/python3", str(root / "mapping_cloud.py"),
                            "--cloud-topic", LaunchConfiguration("cloud_topic"),
                            "--ground-z", LaunchConfiguration("ground_z"),
                            "--frames", LaunchConfiguration("accumulation_frames")], output="screen"),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(root / "go2_mapping.launch.py")),
                                 launch_arguments={"parameters": LaunchConfiguration("parameters"),
                                                   "cloud_topic": "/dddmr/lidar_points",
                                                   "ground_z": LaunchConfiguration("ground_z")}.items()),
    ])
