"""Stream the two approved ROS sensor topics over SSH stdout."""
import argparse
import statistics
import select
import struct
import sys
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from rclpy.serialization import serialize_message
from sensor_msgs.msg import Imu, PointCloud2
from unitree_go.msg import LowState

STREAMS = ((1, PointCloud2, "/utlidar/cloud"), (2, Imu, "/utlidar/imu"))
HEADER = struct.Struct("!BIq")
CLOCK_REPLY = struct.Struct("!q")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=0)
    duration = parser.parse_args().duration
    sink = sys.stdout.buffer
    # The relay brackets these replies with its own clock before streaming.
    while True:
        request = sys.stdin.buffer.read(1)
        if request == b"T":
            sink.write(CLOCK_REPLY.pack(time.time_ns()))
            sink.flush()
        elif request == b"S":
            break
        else:
            return
    rclpy.init(args=[])
    node = rclpy.create_node("go2_dock_sensor_source")
    ages = []
    sensor_offset = [None]

    def observe_clock(message):
        ns=message.header.stamp.sec*10**9+message.header.stamp.nanosec
        ages.append(time.time_ns()-ns)
        send(message,3)
        if len(ages)>=100:
            sensor_offset[0]=int(statistics.median(ages[-100:]))

    clock_sub = node.create_subscription(Imu, "/utlidar/imu", observe_clock, qos_profile_sensor_data)

    def send_body(state):
        if sensor_offset[0] is None:
            return
        message=Imu()
        ns=time.time_ns()-sensor_offset[0]
        message.header.stamp.sec,message.header.stamp.nanosec=divmod(ns,10**9)
        message.header.frame_id="go2_chassis_imu"
        a,g,q=state.imu_state.accelerometer,state.imu_state.gyroscope,state.imu_state.quaternion
        message.linear_acceleration.x,message.linear_acceleration.y,message.linear_acceleration.z=map(float,a)
        message.angular_velocity.x,message.angular_velocity.y,message.angular_velocity.z=map(float,g)
        message.orientation.w,message.orientation.x,message.orientation.y,message.orientation.z=map(float,q)
        send(message,2)

    def send(message, kind):
        received_ns = time.time_ns()
        data = serialize_message(message)
        sink.write(HEADER.pack(kind, len(data), received_ns) + data)
        sink.flush()

    subscriptions = [
        node.create_subscription(PointCloud2,"/utlidar/cloud",lambda msg:send(msg,1),qos_profile_sensor_data),
        node.create_subscription(LowState,"/lowstate",send_body,qos_profile_sensor_data),
        clock_sub,
    ]
    deadline = time.monotonic() + duration if duration else float("inf")
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            if select.select([sys.stdin], [], [], 0)[0] and not sys.stdin.buffer.read1(1):
                break
            rclpy.spin_once(node, timeout_sec=0.1)
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        for subscription in subscriptions:
            node.destroy_subscription(subscription)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
