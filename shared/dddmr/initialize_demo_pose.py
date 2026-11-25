#!/usr/bin/env python3
"""Seed MCL once from Gazebo odometry, only for the matching Go2 demo world/map."""
import json
import math
import os
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data


def main():
    if os.environ.get('ROS_DOMAIN_ID') != '83' or os.environ.get('ROS_LOCALHOST_ONLY') != '1':
        raise RuntimeError('This initializer is only for the local demo in domain 83.')
    rclpy.init()
    node = rclpy.create_node('initialize_go2_demo_pose')
    state = {}
    subscriptions = [
        node.create_subscription(Odometry, '/odom', lambda m: state.update(odom=m), qos_profile_sensor_data),
        node.create_subscription(PointCloud2, '/map1/mapcloud',
                                 lambda m: state.update(map_ready=m.width * m.height > 0),
                                 QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)),
        node.create_subscription(PoseWithCovarianceStamped, '/mcl_pose',
                                 lambda m: state.update(estimate=m), qos_profile_sensor_data),
    ]
    publisher = node.create_publisher(PoseWithCovarianceStamped, '/initial_3d_pose', 2)
    try:
        deadline = time.monotonic() + 45
        while not (state.get('map_ready') and 'odom' in state and publisher.get_subscription_count()):
            if time.monotonic() >= deadline:
                raise TimeoutError('Waiting for Gazebo odometry, demo map and MCL subscriber.')
            rclpy.spin_once(node, timeout_sec=0.1)
        providers = node.get_publishers_info_by_topic('/odom')
        if not providers or any(p.node_name != 'gz_to_odom_tf_filtered' for p in providers):
            raise RuntimeError('Refusing odometry that is not from the demo Gazebo pose bridge.')
        odom = state['odom']
        if odom.header.frame_id != 'odom' or odom.child_frame_id != 'base_link':
            raise RuntimeError('Unexpected demo odometry frames.')
        p, q = odom.pose.pose.position, odom.pose.pose.orientation
        if not all(math.isfinite(v) for v in [p.x, p.y, p.z, q.x, q.y, q.z, q.w]):
            raise RuntimeError('Invalid odometry pose.')
        seed = PoseWithCovarianceStamped()
        seed.header = odom.header
        seed.header.frame_id = 'map'
        seed.pose.pose = odom.pose.pose
        for index, variance in zip([0, 7, 14, 21, 28, 35], [.01, .01, .01, .0025, .0025, .01]):
            seed.pose.covariance[index] = variance
        publisher.publish(seed)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        estimate = state.get('estimate')
        error_xy = (math.hypot(estimate.pose.pose.position.x - p.x,
                               estimate.pose.pose.position.y - p.y) if estimate else None)
        print(json.dumps({'source': 'Gazebo model-derived /odom; one-time demo initialization',
                          'seed_position': [p.x, p.y, p.z],
                          'estimate_error_xy': error_xy,
                          'estimate_position': ([estimate.pose.pose.position.x, estimate.pose.pose.position.y,
                                                 estimate.pose.pose.position.z] if estimate else None)}, indent=2))
        if error_xy is None or not math.isfinite(error_xy) or error_xy > 0.8:
            raise RuntimeError('MCL is not near the supplied demo initial pose; inspect before sending a goal.')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
