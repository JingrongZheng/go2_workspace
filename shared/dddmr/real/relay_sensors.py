"""Receive raw Go2 sensors through a verified SSH connection and publish locally."""
import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import select
import shlex
import struct
import subprocess
import time
import zlib

import rclpy
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import Imu, PointCloud2

HEADER = struct.Struct("!BIq")
CLOCK_REPLY = struct.Struct("!q")
STREAMS = {1: (PointCloud2, "/go2/relay/cloud"), 2: (Imu, "/go2/relay/imu"),
           3: (Imu, "/go2/relay/chassis_imu")}
MAX_PAYLOAD = 8 * 1024 * 1024


def remote_command(duration, include_chassis_imu=False):
    source = Path(__file__).with_name("dock_sensor_source.py").read_text()
    config = ('<CycloneDDS><Domain><General><NetworkInterfaceAddress>eth10'
              '</NetworkInterfaceAddress></General></Domain></CycloneDDS>')
    chassis_setup = ("source /unitree/module/graph_pid_ws/install/unitree_go/share/unitree_go/local_setup.bash >&2; "
                     if include_chassis_imu else "")
    chassis_flag = " --include-chassis-imu" if include_chassis_imu else ""
    return (
        "set -e; source /opt/ros/foxy/setup.bash >&2; "
        "source ~/cyclonedds_ws/install/local_setup.bash >&2; "
        + chassis_setup +
        "export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp; "
        f"export CYCLONEDDS_URI={shlex.quote(config)}; "
        f"exec /usr/bin/python3 -u -c {shlex.quote(source)} --duration {duration}{chassis_flag}"
    )


def read_exact(output, size, eof_ok=False, timeout=8):
    data = bytearray()
    fd = output.fileno()
    deadline = time.monotonic() + timeout
    while len(data) < size:
        if not select.select([fd], [], [], max(0, deadline - time.monotonic()))[0]:
            raise TimeoutError(
                "Timed out waiting for the dock sensor stream "
                f"({timeout:g}s; received {len(data)}/{size} bytes). "
                "Check dock USB/WiFi and SSH. Mapping data continuity is no longer assured; "
                "save the current map before stopping its builder, then restart acquisition "
                "and the LIO/mapping session. Do not resume across missing IMU samples.")
        chunk = os.read(fd, size - len(data))
        if not chunk:
            if eof_ok and not data:
                return None
            raise RuntimeError("Truncated dock response")
        data.extend(chunk)
    return bytes(data)


def measure_pc_minus_dock(process):
    samples = []
    for attempt in range(9):
        start_monotonic = time.monotonic_ns()
        start = time.time_ns()
        process.stdin.write(b"T")
        dock, = CLOCK_REPLY.unpack(read_exact(process.stdout, CLOCK_REPLY.size, timeout=40 if not attempt else 8))
        end = time.time_ns()
        roundtrip = time.monotonic_ns() - start_monotonic
        if abs(end - start - roundtrip) < 5_000_000:
            samples.append((roundtrip, (start + end) // 2 - dock))
    if not samples:
        raise RuntimeError("PC clock changed during calibration; retry the relay")
    roundtrip, offset = min(samples)
    print(json.dumps({"pc_minus_dock_s": offset / 1e9, "clock_probe_roundtrip_s": roundtrip / 1e9}),
          flush=True)
    return offset


def receive_frames(output):
    initial_timeout = 40
    while rclpy.ok():
        header = read_exact(output, HEADER.size, eof_ok=True, timeout=initial_timeout)
        initial_timeout = 8
        if header is None:
            return
        kind, size, dock_receive_ns = HEADER.unpack(header)
        if kind not in STREAMS or not 0 < size <= MAX_PAYLOAD:
            raise RuntimeError("Invalid sensor frame header")
        payload = read_exact(output, size)
        inflater = zlib.decompressobj()
        data = inflater.decompress(payload, MAX_PAYLOAD + 1)
        if len(data) > MAX_PAYLOAD or not inflater.eof or inflater.unused_data:
            raise RuntimeError("Invalid compressed sensor payload")
        message = deserialize_message(data, STREAMS[kind][0])
        stamp = message.header.stamp
        source_ns = stamp.sec * 1_000_000_000 + stamp.nanosec
        yield kind, message, source_ns, dock_receive_ns


def estimate_sensor_offset(samples):
    # The low end of observed ages is least affected by DDS scheduling delay.
    return sorted(samples)[len(samples) // 10]


def relay(node, output, stamp_offset_ns, pc_minus_dock_ns, include_chassis_imu=False):
    auto = stamp_offset_ns is None
    sensor_offset = None
    imu_ages = []
    previous_source_ns = {}
    started = None
    active_streams = {k: v for k, v in STREAMS.items() if k != 3 or include_chassis_imu}
    publishers = {kind: node.create_publisher(cls, topic, 10)
                  for kind, (cls, topic) in active_streams.items()}
    stats = {kind: {"topic": topic, "samples": 0} for kind, (_, topic) in active_streams.items()}
    try:
        for kind, message, source_ns, dock_receive_ns in receive_frames(output):
            now = time.monotonic()
            if started is None:
                started = now
            if auto:
                if source_ns <= previous_source_ns.get(kind, 0):
                    raise RuntimeError("Sensor timestamps stopped increasing; restart the relay to resync")
                previous_source_ns[kind] = source_ns
                if kind == 2:
                    imu_ages.append(dock_receive_ns - source_ns)
                if stamp_offset_ns is None:
                    if len(imu_ages) >= 25:
                        sensor_offset = estimate_sensor_offset(imu_ages)
                        stamp_offset_ns = pc_minus_dock_ns + sensor_offset
                        imu_ages.clear()
                        print(json.dumps({"clock_mode": "auto", "common_stamp_offset_s": stamp_offset_ns / 1e9,
                                          "dock_minus_sensor_s": sensor_offset / 1e9}), flush=True)
                    elif now - started > 5:
                        raise RuntimeError("Not enough IMU samples to align the sensor clock (need 25)")
                    continue
                if len(imu_ages) >= 250:
                    if abs(estimate_sensor_offset(imu_ages) - sensor_offset) > 100_000_000:
                        raise RuntimeError("Sensor clock or delivery changed; restart the relay to resync")
                    imu_ages.clear()
            corrected_ns = source_ns + stamp_offset_ns
            pc_age_ns = time.time_ns() - corrected_ns
            if auto and not -100_000_000 <= pc_age_ns <= 750_000_000:
                raise RuntimeError("Corrected sensor timestamp outside the live window; restart the relay")
            entry = stats[kind]
            if not entry["samples"]:
                sample = {"frame_id": message.header.frame_id, "source_stamp_ns": source_ns,
                          "published_stamp_ns": corrected_ns, "pc_age_ms": round(pc_age_ns / 1e6, 2)}
                if kind == 1:
                    sample["points"] = message.width * message.height
                    sample["fields"] = [field.name for field in message.fields]
                print(json.dumps({"topic": entry["topic"], "first": sample}), flush=True)
                entry["first"] = now
            if stamp_offset_ns:
                stamp = message.header.stamp
                stamp.sec, stamp.nanosec = divmod(corrected_ns, 1_000_000_000)
            publishers[kind].publish(message)
            entry["last"] = now
            entry["samples"] += 1
    finally:
        for entry in stats.values():
            initial = entry.pop("first", None)
            final = entry.pop("last", None)
            if initial is not None and final > initial:
                entry["hz"] = round((entry["samples"] - 1) / (final - initial), 2)
            print(json.dumps(entry), flush=True)
    return all(entry["samples"] > 0 for entry in stats.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=ipaddress.IPv4Address, default="192.168.110.87")
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--duration", type=float, default=0)
    parser.add_argument("--include-chassis-imu", action="store_true",
                        help="Also publish /go2/relay/chassis_imu with approximate dock-receive timing")
    clock = parser.add_mutually_exclusive_group()
    clock.add_argument("--raw-stamps", action="store_true", help="Publish unchanged source timestamps")
    clock.add_argument("--stamp-offset-seconds", type=float,
                       help="Use this constant offset instead of automatic alignment")
    args = parser.parse_args()
    stamp_offset_ns = None
    if args.raw_stamps:
        stamp_offset_ns = 0
    elif args.stamp_offset_seconds is not None:
        offset_ns = args.stamp_offset_seconds * 1e9
        if not math.isfinite(offset_ns):
            parser.error("Timestamp offset must be finite")
        stamp_offset_ns = round(offset_ns)
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("Duration must be finite and nonnegative")
    command = ["ssh", "-T", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=yes",
               "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2"]
    if args.socket:
        command.extend(["-o", "BatchMode=yes", "-S", str(args.socket)])
    command.extend([f"unitree@{args.host}", "bash -c " + shlex.quote(remote_command(args.duration, args.include_chassis_imu))])
    rclpy.init(args=[])
    node = rclpy.create_node("go2_ssh_sensor_relay")
    try:
        with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0) as process:
            try:
                offset = measure_pc_minus_dock(process) if stamp_offset_ns is None else 0
                process.stdin.write(b"S")
                received = relay(node, process.stdout, stamp_offset_ns, offset, args.include_chassis_imu)
                return 0 if process.wait(timeout=6) == 0 and received else 1
            except (RuntimeError, TimeoutError, OSError) as error:
                node.get_logger().error(str(error))
                return 1
            except KeyboardInterrupt:
                return 130
            finally:
                process.stdin.close()
                if process.poll() is None:
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
