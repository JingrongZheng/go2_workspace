#!/usr/bin/env python3
"""Bounded read-only observation of the local simulation/navigation ROS graph."""
import argparse
import json
import math
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry, Path
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import PointCloud2
from tf2_msgs.msg import TFMessage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=15)
    args = parser.parse_args()
    if not 0 < args.duration <= 120:
        parser.error('duration must be in (0,120]')
    types = {'rosgraph_msgs/msg/Clock': Clock, 'sensor_msgs/msg/PointCloud2': PointCloud2,
             'nav_msgs/msg/Odometry': Odometry, 'geometry_msgs/msg/Twist': Twist,
             'nav_msgs/msg/Path': Path, 'tf2_msgs/msg/TFMessage': TFMessage}
    rclpy.init()
    node = rclpy.create_node('dddmr_local_runtime_probe')
    counts, subscriptions, graph, pairs = {}, {}, {}, set()

    def receive(msg, topic):
        item = counts[topic]
        item['messages'] += 1
        if isinstance(msg, Clock):
            item['last_clock'] = msg.clock.sec + msg.clock.nanosec / 1e9
            item.setdefault('first_clock', item['last_clock'])
        elif isinstance(msg, PointCloud2):
            valid = (msg.width * msg.height > 0 and msg.point_step > 0
                     and len(msg.data) == msg.row_step * msg.height)
            item['nonempty_frames'] = item.get('nonempty_frames', 0) + int(valid)
            item['last_points'] = msg.width * msg.height
            item['frame_id'] = msg.header.frame_id
        elif isinstance(msg, Odometry):
            p = msg.pose.pose.position
            xyz = [p.x, p.y, p.z]
            item.setdefault('first_position', xyz)
            item['last_position'] = xyz
            item['finite_pose'] = all(math.isfinite(x) for x in xyz)
            item['frames'] = [msg.header.frame_id, msg.child_frame_id]
        elif isinstance(msg, Twist):
            speed = [msg.linear.x, msg.linear.y, msg.angular.z]
            item['nonzero_commands'] = item.get('nonzero_commands', 0) + int(any(abs(x) > 1e-5 for x in speed))
            item['last_command'] = speed
        elif isinstance(msg, Path):
            item['max_path_poses'] = max(item.get('max_path_poses', 0), len(msg.poses))
        elif isinstance(msg, TFMessage):
            pairs.update((t.header.frame_id, t.child_frame_id) for t in msg.transforms)

    start, scan = time.monotonic(), 0.0
    try:
        while time.monotonic() - start < args.duration:
            if time.monotonic() >= scan:
                graph.update(dict(node.get_topic_names_and_types()))
                for topic, available in graph.items():
                    if topic in subscriptions:
                        continue
                    cls = next((types[t] for t in available if t in types), None)
                    if cls is not None:
                        counts[topic] = {'messages': 0}
                        qos = (QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
                               if topic == '/tf_static' else qos_profile_sensor_data)
                        subscriptions[topic] = node.create_subscription(
                            cls, topic, lambda msg, name=topic: receive(msg, name), qos)
                scan = time.monotonic() + 1
            rclpy.spin_once(node, timeout_sec=0.1)
        print(json.dumps({'seconds': round(time.monotonic() - start, 2), 'topics': graph,
                          'observations': counts, 'tf_edges': sorted(pairs)}, indent=2), flush=True)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
