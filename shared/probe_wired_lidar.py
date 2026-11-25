#!/usr/bin/env python3
"""Read-only discovery and PointCloud2 reception check; does not identify hardware by topic name."""
import argparse
import json
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=15)
    args = parser.parse_args()
    if not 0 < args.duration <= 300:
        parser.error('--duration must be between 0 and 300 seconds')
    rclpy.init()
    node = rclpy.create_node('wired_lidar_readonly_probe')
    subscriptions, counts, topics = {}, {}, {}
    started = time.monotonic()
    next_scan = started
    try:
        while rclpy.ok() and time.monotonic() - started < args.duration:
            if time.monotonic() >= next_scan:
                topics.update(dict(node.get_topic_names_and_types()))
                for topic, types in sorted(topics.items()):
                    if 'sensor_msgs/msg/PointCloud2' not in types or topic in subscriptions:
                        continue
                    counts[topic] = {'frames': 0, 'nonempty_frames': 0, 'invalid_layout_frames': 0}

                    def receive(msg, name=topic):
                        stats = counts[name]
                        stats['frames'] += 1
                        points = msg.width * msg.height
                        valid = (points > 0 and msg.point_step > 0
                                 and msg.row_step >= msg.width * msg.point_step
                                 and len(msg.data) == msg.height * msg.row_step
                                 and {'x', 'y', 'z'}.issubset({f.name for f in msg.fields}))
                        stats['nonempty_frames'] += int(valid)
                        stats['invalid_layout_frames'] += int(not valid)
                        if stats['frames'] == 1:
                            stats['first_monotonic'] = time.monotonic()
                            print(json.dumps({'topic': name, 'first_frame': {
                                'frame_id': msg.header.frame_id, 'stamp_sec': msg.header.stamp.sec,
                                'width': msg.width, 'height': msg.height, 'point_step': msg.point_step,
                                'data_bytes': len(msg.data), 'fields': [f.name for f in msg.fields],
                                'nonempty_xyz_layout': valid}}, ensure_ascii=False), flush=True)
                        stats['last_monotonic'] = time.monotonic()

                    subscriptions[topic] = node.create_subscription(
                        PointCloud2, topic, receive, qos_profile_sensor_data)
                    print('Subscribing PointCloud2: ' + topic, flush=True)
                next_scan = time.monotonic() + 1
            rclpy.spin_once(node, timeout_sec=0.1)
        print('Discovered topics: ' + json.dumps(topics, ensure_ascii=False, sort_keys=True), flush=True)
        for topic, stats in counts.items():
            first = stats.pop('first_monotonic', None)
            last = stats.pop('last_monotonic', None)
            stats['observed_hz'] = ((stats['frames'] - 1) / (last - first)
                                    if first is not None and last > first else None)
            print(json.dumps({'topic': topic, **stats}, ensure_ascii=False), flush=True)
        print('Hardware source is unconfirmed until driver/endpoint/wiring is checked.', flush=True)
        return 0 if any(s['nonempty_frames'] for s in counts.values()) else 2
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
