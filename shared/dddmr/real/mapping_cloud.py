"""Motion-compensate L2 scans with LIO odometry for DDDMR projection only."""
import argparse
from collections import deque
import json
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from scipy.spatial.transform import Rotation, Slerp
from sensor_msgs.msg import PointCloud2, PointField
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import StaticTransformBroadcaster


def stamp_seconds(stamp):
    return stamp.sec + stamp.nanosec * 1e-9


class MappingCloud(Node):
    def __init__(self, args):
        super().__init__("go2_dddmr_mapping_cloud")
        self.args = args
        calibration = json.loads(Path(__file__).with_name("go2_published_cloud_geometry.json").read_text())
        self.source_frame = calibration["source_frame"]
        self.body_from_cloud = np.array(calibration["rotation_matrix"])
        self.sensor_origin = np.array(calibration["translation_m"])
        self.poses = deque()
        self.pending = deque(maxlen=128)
        self.world_scans = deque(maxlen=args.frames)
        self.counts = {"input": 0, "output": 0, "before_lio": 0, "odom_overlap_skipped": 0}
        self.output = self.create_publisher(PointCloud2, "/dddmr/lidar_points", 10)
        self.sub_cloud = self.create_subscription(PointCloud2, args.cloud_topic, self.cloud, 20)
        self.sub_odom = self.create_subscription(Odometry, "/odom", self.odom, 100)
        self.static_tf = StaticTransformBroadcaster(self)
        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = "base_link"
        transform.child_frame_id = "dddmr_lidar"
        transform.transform.translation.x, transform.transform.translation.y, transform.transform.translation.z = map(float, self.sensor_origin)
        transform.transform.rotation.w = 1.
        self.static_tf.sendTransform(transform)
        self.timer = self.create_timer(5., self.report)

    def report(self):
        self.get_logger().info(json.dumps({**self.counts, "pending": len(self.pending), "motion_compensated_frames": self.args.frames}))

    def odom(self, msg):
        if msg.header.frame_id != "odom" or msg.child_frame_id != "base_link":
            raise ValueError("Mapping adapter requires odom -> base_link odometry")
        t = stamp_seconds(msg.header.stamp)
        if self.poses and t <= self.poses[-1][0]:
            backstep = self.poses[-1][0] - t
            if backstep <= 0.05:
                self.counts["odom_overlap_skipped"] += 1
                if self.counts["odom_overlap_skipped"] <= 5 or self.counts["odom_overlap_skipped"] % 50 == 0:
                    self.get_logger().warn(
                        f"Skipped non-increasing /odom sample (backstep={backstep * 1e3:.3f} ms, "
                        f"total={self.counts['odom_overlap_skipped']})"
                    )
                return
            raise ValueError(f"Odometry timestamp regressed by {backstep:.6f} s")
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        self.poses.append((t, [p.x, p.y, p.z], [q.x, q.y, q.z, q.w]))
        while len(self.poses) > 2 and self.poses[1][0] < t - 4.:
            self.poses.popleft()
        self.drain()

    def cloud(self, msg):
        if msg.header.frame_id != self.source_frame or msg.height != 1:
            raise ValueError("Unexpected source cloud frame or organized layout")
        fields = {f.name: f for f in msg.fields}
        if not all(k in fields and fields[k].datatype == PointField.FLOAT32 for k in ("x", "y", "z", "intensity", "time")):
            raise ValueError("Expected FLOAT32 xyz/intensity/time fields")
        data = np.stack([np.ndarray((msg.width,), dtype=">f4" if msg.is_bigendian else "<f4", buffer=msg.data,
                                    offset=fields[k].offset, strides=(msg.point_step,)) for k in ("x", "y", "z", "intensity", "time")], axis=1)
        data = data[np.isfinite(data).all(axis=1)]
        if not len(data):
            return
        if data[:, 4].min() < 0 or data[:, 4].max() > .2:
            raise ValueError("Point timestamps must be relative seconds within one L2 scan")
        begin = stamp_seconds(msg.header.stamp)
        self.pending.append((begin, begin + float(data[:, 4].max()), data))
        self.counts["input"] += 1
        self.drain()

    def drain(self):
        while len(self.poses) >= 2 and self.pending:
            begin, end, raw = self.pending[0]
            if end > self.poses[-1][0]:
                return  # Wait for the LIO trajectory to cover the full scan.
            self.pending.popleft()
            if begin < self.poses[0][0]:
                self.counts["before_lio"] += 1
                continue
            xyz = raw[:, :3]
            body = xyz @ self.body_from_cloud.T + self.sensor_origin
            distance = np.linalg.norm(xyz, axis=1)
            self_return = ((np.abs(body[:, 0]) < .35) & (np.abs(body[:, 1]) < .155)
                           & (body[:, 2] > self.args.ground_z) & (body[:, 2] < self.args.ground_z + .4))
            valid = (distance >= .1) & (distance <= 20.) & ~self_return
            body, raw = body[valid], raw[valid]
            if not len(raw):
                continue
            times = np.array([p[0] for p in self.poses])
            positions = np.array([p[1] for p in self.poses])
            rotations = Rotation.from_quat([p[2] for p in self.poses])
            relative = times - times[0]
            point_times = np.clip(begin + raw[:, 4].astype(np.float64) - times[0], 0.0, relative[-1])
            slerp = Slerp(relative, rotations)
            world_xyz = slerp(point_times).apply(body)
            world_xyz += np.stack([np.interp(point_times, relative, positions[:, k]) for k in range(3)], axis=1)
            self.world_scans.append((world_xyz, raw[:, 3]))
            if len(self.world_scans) < self.args.frames:
                continue
            # Accumulate in odom, then express every point at the latest scan
            # end in a sensor frame whose axes are parallel to base_link.
            end_time = float(np.clip(end - times[0], 0.0, relative[-1]))
            end_rotation = slerp(end_time)
            end_position = np.array([np.interp(end_time, relative, positions[:, k]) for k in range(3)])
            world_origin = end_position + end_rotation.apply(self.sensor_origin)
            all_xyz = np.concatenate([x[0] for x in self.world_scans])
            all_intensity = np.concatenate([x[1] for x in self.world_scans])
            output_xyz = end_rotation.inv().apply(all_xyz - world_origin)
            packed = np.column_stack((output_xyz, all_intensity)).astype("<f4")
            msg = PointCloud2()
            ns = round(end * 1e9)
            msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(ns, 10**9)
            msg.header.frame_id = "dddmr_lidar"
            msg.height, msg.width, msg.point_step = 1, len(packed), 16
            msg.row_step = msg.width * msg.point_step
            msg.is_dense, msg.is_bigendian = True, False
            msg.fields = [PointField(name=name, offset=4*i, datatype=PointField.FLOAT32, count=1)
                          for i, name in enumerate(("x", "y", "z", "intensity"))]
            msg.data = packed.tobytes()
            self.output.publish(msg)
            self.counts["output"] += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-topic", required=True)
    parser.add_argument("--ground-z", type=float, required=True)
    parser.add_argument("--frames", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.frames <= 8 or not np.isfinite(args.ground_z):
        parser.error("Require 1..8 scans and a finite ground height")
    rclpy.init(args=[])
    node = MappingCloud(args)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.report()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
