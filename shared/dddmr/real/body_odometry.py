"""Convert Point-LIO's internal IMU odometry to the Go2 body origin."""
import argparse

import numpy as np
import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from scipy.spatial.transform import Rotation


class BodyOdometry(Node):
    def __init__(self, translation, pitch, source_child="l2_imu"):
        super().__init__("go2_body_odometry")
        self.offset = np.array(translation)
        self.source_child = source_child
        self.imu_from_body = Rotation.from_euler("y", pitch)
        self.output = self.create_publisher(Odometry, "/odom", 10)
        self.subscription = self.create_subscription(
            Odometry, "/aft_mapped_to_init", self.convert, 10
        )

    def convert(self, source):
        if source.header.frame_id != "odom" or source.child_frame_id != self.source_child:
            self.get_logger().error(f"Expected odom -> {self.source_child}", throttle_duration_sec=5.0)
            return
        p, q = source.pose.pose.position, source.pose.pose.orientation
        world_from_imu = Rotation.from_quat([q.x, q.y, q.z, q.w])
        world_from_body = world_from_imu * self.imu_from_body
        target = Odometry()
        target.header = source.header
        target.child_frame_id = "base_link"
        position = np.array([p.x, p.y, p.z]) + world_from_imu.apply(self.offset)
        point = target.pose.pose.position
        point.x, point.y, point.z = map(float, position)
        orientation = target.pose.pose.orientation
        orientation.x, orientation.y, orientation.z, orientation.w = map(float, world_from_body.as_quat())
        # The pinned Point-LIO publishes filter velocity in world axes and
        # angular velocity in IMU axes. Include the body-origin lever arm.
        v, w = source.twist.twist.linear, source.twist.twist.angular
        omega = np.array([w.x, w.y, w.z])
        velocity_imu = world_from_imu.inv().apply([v.x, v.y, v.z]) + np.cross(omega, self.offset)
        body_from_imu = self.imu_from_body.inv()
        linear, angular = target.twist.twist.linear, target.twist.twist.angular
        linear.x, linear.y, linear.z = map(float, body_from_imu.apply(velocity_imu))
        angular.x, angular.y, angular.z = map(float, body_from_imu.apply(omega))
        # This Point-LIO mode leaves both input covariances unspecified.
        self.output.publish(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("translation", type=float, nargs=3)
    parser.add_argument("pitch", type=float)
    parser.add_argument("--source-child", default="l2_imu")
    args = parser.parse_args()
    rclpy.init(args=[])
    node = BodyOdometry(args.translation, args.pitch, args.source_child)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
