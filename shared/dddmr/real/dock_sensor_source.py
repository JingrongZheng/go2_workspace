"""Stream the two approved ROS sensor topics over SSH stdout."""
import argparse
import select
import struct
import sys
import time
import zlib

import rclpy
from rclpy.qos import qos_profile_sensor_data
from rclpy.serialization import serialize_message
from sensor_msgs.msg import Imu, PointCloud2

STREAMS = ((1, PointCloud2, "/utlidar/cloud"), (2, Imu, "/utlidar/imu"))
HEADER = struct.Struct("!BIq")
CLOCK_REPLY = struct.Struct("!q")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=0)
    parser.add_argument("--include-chassis-imu", action="store_true")
    args = parser.parse_args()
    duration = args.duration
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
    clock_ages = []
    sensor_clock_offset = None
    def send(message, kind):
        nonlocal sensor_clock_offset
        received_ns = time.time_ns()
        if kind == 2 and sensor_clock_offset is None:
            source_ns = message.header.stamp.sec * 10**9 + message.header.stamp.nanosec
            clock_ages.append(received_ns - source_ns)
            if len(clock_ages) >= 100:
                sensor_clock_offset = sorted(clock_ages)[len(clock_ages) // 10]
        payload = zlib.compress(serialize_message(message), level=1)
        sink.write(HEADER.pack(kind, len(payload), received_ns))
        sink.write(payload)
        sink.flush()

    subscriptions = [
        node.create_subscription(cls, topic, lambda msg, k=kind: send(msg, k),
                                 qos_profile_sensor_data)
        for kind, cls, topic in STREAMS
    ]
    if args.include_chassis_imu:
        from unitree_go.msg import LowState
        tick_samples = []
        tick_to_dock_ns = None
        previous_tick = None
        tick_wrap = 0

        def send_chassis(state):
            nonlocal tick_to_dock_ns, previous_tick, tick_wrap
            received_ns = time.time_ns()
            tick = int(state.tick)
            if previous_tick is not None:
                if tick == previous_tick:
                    return
                if tick < previous_tick:
                    if previous_tick - tick > 2**31:
                        tick_wrap += 2**32
                    else:
                        raise RuntimeError("LowState tick reset; restart the relay to resync")
            previous_tick = tick
            native_ns = (tick + tick_wrap) * 1_000_000
            if tick_to_dock_ns is None:
                tick_samples.append(received_ns - native_ns)
                if len(tick_samples) < 100:
                    return
                tick_to_dock_ns = min(tick_samples)
                print("Chassis IMU: native millisecond tick anchored to dock receive clock; not hardware synchronized", file=sys.stderr)
            if sensor_clock_offset is None:
                return
            message = Imu()
            # Preserve native sampling intervals. The epoch is estimated from
            # minimum dock reception delay, not hardware synchronized to L2.
            ns = native_ns + tick_to_dock_ns - sensor_clock_offset
            message.header.stamp.sec, message.header.stamp.nanosec = divmod(ns, 10**9)
            message.header.frame_id = "go2_chassis_imu"
            imu = state.imu_state
            message.linear_acceleration.x, message.linear_acceleration.y, message.linear_acceleration.z = map(float, imu.accelerometer)
            message.angular_velocity.x, message.angular_velocity.y, message.angular_velocity.z = map(float, imu.gyroscope)
            message.orientation.w, message.orientation.x, message.orientation.y, message.orientation.z = map(float, imu.quaternion)
            send(message, 3)

        subscriptions.append(node.create_subscription(
            LowState, "/lowstate", send_chassis, qos_profile_sensor_data))
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
