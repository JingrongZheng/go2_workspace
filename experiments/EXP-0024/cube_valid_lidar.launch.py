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
                {"use_sim_time": False, "cube_side_length": 1000.,
                 "common.lid_topic": LaunchConfiguration("cloud_topic"),
                 "common.imu_topic": LaunchConfiguration("imu_topic"),
                 "odom_header_frame_id": "odom", "odom_child_frame_id": "l2_imu",
                 "odometry.publish_odometry_without_downsample": False,
                 "pcd_save.pcd_save_en": False,
                 "filter_size_surf": 0.1, "filter_size_map": 0.1},
            ],
        ),
        RegisterEventHandler(OnProcessExit(target_action=play, on_exit=[Shutdown()])),
        play,
    ])
