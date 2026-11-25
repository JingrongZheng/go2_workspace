"""Launch DDDMR map building with external odometry and a raw lidar topic."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("parameters", description="Real DDDMR mapping parameter YAML"),
        DeclareLaunchArgument("cloud_topic", description="Verified raw L2 PointCloud2 topic"),
        DeclareLaunchArgument("ground_z", description="Standing ground Z in base_link"),
        Node(package="tf2_ros", executable="static_transform_publisher",
             arguments=["--z", LaunchConfiguration("ground_z"), "--frame-id", "base_link",
                        "--child-frame-id", "base_footprint"]),
        Node(
            package="lego_loam_bor", executable="lego_loam", output="screen",
            parameters=[LaunchConfiguration("parameters"), {"use_sim_time": False}],
            remappings=[("/lslidar_point_cloud", LaunchConfiguration("cloud_topic")),
                        ("/aft_mapped_to_init", "/dddmr/aft_mapped_to_init")],
        ),
    ])
