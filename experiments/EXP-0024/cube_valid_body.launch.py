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
                {"use_sim_time": False,
                 "use_imu_as_input": True, "cube_side_length": 1000., "init_map_size": 20000, "mapping.plane_thr": 0.03,
                 "mapping.extrinsic_R": [0.5261139320680797, -0.8101357959786011, 0.25861964843758883, -0.8386681536966942, -0.5446427526117121, 1.585844622301047e-06, 0.1408540324550263, -0.21689689739979073, -0.9659792324059058],
                 "mapping.extrinsic_T": [0.30773, 0., -0.04232],
                 "common.lid_topic": LaunchConfiguration("cloud_topic"),
                 "common.imu_topic": LaunchConfiguration("imu_topic"),
                 "odom_header_frame_id": "odom", "odom_child_frame_id": "go2_chassis_imu",
                 "odometry.publish_odometry_without_downsample": False,
                 "pcd_save.pcd_save_en": False,
                 "filter_size_surf": 0.1, "filter_size_map": 0.1},
            ],
        ),
        RegisterEventHandler(OnProcessExit(target_action=play, on_exit=[Shutdown()])),
        play,
    ])
