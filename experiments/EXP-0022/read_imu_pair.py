"""Read Go2 LiDAR IMU and chassis IMU on the dock. Output JSON lines."""
import argparse
import json
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Imu
from unitree_go.msg import LowState

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--seconds", type=int, default=6, choices=range(1, 121))
seconds = parser.parse_args().seconds
rclpy.init(args=[])
node = rclpy.create_node("sensor_frame_audit")
counts = {"lidar": 0, "body": 0}


def emit(kind, accel, gyro, quaternion, stamp):
    counts[kind] += 1
    print(json.dumps({"stream": kind, "dock_receive_ns": time.time_ns(),
                      "source_stamp_or_tick": stamp, "accel": list(map(float, accel)),
                      "gyro": list(map(float, gyro)), "quaternion_wxyz": list(map(float, quaternion))}))


def lidar(msg):
    a, g, q = msg.linear_acceleration, msg.angular_velocity, msg.orientation
    emit("lidar", (a.x, a.y, a.z), (g.x, g.y, g.z), (q.w, q.x, q.y, q.z),
         msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec)


def body(msg):
    imu = msg.imu_state
    emit("body", imu.accelerometer, imu.gyroscope, imu.quaternion, msg.tick)


subs = [
    node.create_subscription(Imu, "/utlidar/imu", lidar, qos_profile_sensor_data),
    node.create_subscription(LowState, "/lf/lowstate", body, qos_profile_sensor_data),
]
end = time.monotonic() + seconds
try:
    while rclpy.ok() and time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0.1)
    print(json.dumps({"counts": counts}))
finally:
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
