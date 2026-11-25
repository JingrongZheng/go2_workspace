"""L2 published point cloud + full chassis IMU; sensor-only, no control node."""
import json
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, RegisterEventHandler, Shutdown
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from scipy.spatial.transform import Rotation


def generate_launch_description():
    root = Path(__file__).parent
    geometry = json.loads((root / "go2_nominal_geometry.json").read_text())
    published = json.loads((root / "go2_published_cloud_geometry.json").read_text())
    imu = next(x for x in geometry["transforms"] if x["parent"] == "base" and x["child"] == "imu")
    radar = next(x for x in geometry["transforms"] if x["parent"] == "base" and x["child"] == "radar")
    # The official chassis IMU axes coincide with base; only the origin differs.
    if max(abs(v) for v in imu["rpy_rad"]) > 1e-9:
        raise ValueError("Chassis profile requires identity URDF base-to-imu rotation")
    base_in_imu = [-x for x in imu["translation_m"]]
    cloud_in_imu = [x - y for x, y in zip(published["translation_m"], imu["translation_m"])]

    def static(name, parent, child, xyz, quaternion):
        arguments = [item for axis, value in zip("xyz", xyz) for item in (f"--{axis}", str(value))]
        arguments += [item for axis, value in zip("xyzw", quaternion) for item in (f"--q{axis}", str(value))]
        return Node(package="tf2_ros", executable="static_transform_publisher", name=name,
                    arguments=arguments + ["--frame-id", parent, "--child-frame-id", child])

    play = ExecuteProcess(cmd=["ros2", "bag", "play", "/recorded-bag", "--delay", "3", "--topics",
                               LaunchConfiguration("cloud_topic"), LaunchConfiguration("imu_topic")],
                          condition=IfCondition(LaunchConfiguration("play_bag")), output="screen")
    return LaunchDescription([
        DeclareLaunchArgument("play_bag", default_value="false"),
        DeclareLaunchArgument("cloud_topic"), DeclareLaunchArgument("imu_topic"),
        Node(package="point_lio", executable="pointlio_mapping", name="laserMapping", output="screen",
             parameters=[str(Path(get_package_share_directory("point_lio")) / "config/unilidar_l2.yaml"),
                         {"use_sim_time": False, "cube_side_length": 1000., "init_map_size": 20000,
                          "mapping.plane_thr": 0.03, "use_imu_as_input": True,
                          "mapping.extrinsic_R": [v for row in published["rotation_matrix"] for v in row],
                          "mapping.extrinsic_T": cloud_in_imu,
                          "common.lid_topic": LaunchConfiguration("cloud_topic"),
                          "common.imu_topic": LaunchConfiguration("imu_topic"),
                          "odom_header_frame_id": "odom", "odom_child_frame_id": "go2_chassis_imu",
                          "odometry.publish_odometry_without_downsample": False,
                          "pcd_save.pcd_save_en": False, "filter_size_surf": 0.1, "filter_size_map": 0.1}]),
        ExecuteProcess(cmd=["/usr/bin/python3", str(root / "body_odometry.py"), *map(str, base_in_imu),
                            "0", "--source-child", "go2_chassis_imu"], output="screen"),
        static("chassis_imu_to_base", "go2_chassis_imu", "base_link", base_in_imu, [0, 0, 0, 1]),
        static("base_to_model_radar", "base_link", "radar", radar["translation_m"],
               Rotation.from_euler("xyz", radar["rpy_rad"]).as_quat()),
        static("base_to_published_cloud", "base_link", published["source_frame"], published["translation_m"],
               Rotation.from_matrix(published["rotation_matrix"]).as_quat()),
        static("published_cloud_alias", published["source_frame"], "lidar_link", [0, 0, 0], [0, 0, 0, 1]),
        RegisterEventHandler(OnProcessExit(target_action=play, on_exit=[Shutdown()])), play,
    ])
