"""L2/chassis Point-LIO and DDDMR mapping together; no motion control."""
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    root = Path(__file__).parent

    def include(filename, arguments):
        return IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(root / filename)),
            launch_arguments=arguments.items())

    return LaunchDescription([
        DeclareLaunchArgument("cloud_topic", default_value="/go2/relay/cloud"),
        DeclareLaunchArgument("imu_topic", default_value="/go2/relay/chassis_imu"),
        DeclareLaunchArgument("parameters", default_value=str(root / "config/l2_mapping_lab.yaml")),
        DeclareLaunchArgument("ground_z", default_value="-0.3168676504844956"),
        include("point_lio_chassis.launch.py", {
            "cloud_topic": LaunchConfiguration("cloud_topic"),
            "imu_topic": LaunchConfiguration("imu_topic"), "play_bag": "false"}),
        include("go2_l2_mapping.launch.py", {
            "parameters": LaunchConfiguration("parameters"),
            "cloud_topic": LaunchConfiguration("cloud_topic"),
            "ground_z": LaunchConfiguration("ground_z")}),
    ])
