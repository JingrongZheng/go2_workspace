#!/usr/bin/env python3
"""Bridge Go2 WebRTC telemetry and optional keyboard requests to PC-local ROS 2."""

import argparse
import asyncio
import getpass
import json
import math
import socket
import subprocess
import sys
from pathlib import Path
import time
from unittest.mock import patch

import numpy as np
import rclpy
from rclpy.signals import SignalHandlerOptions
from rosidl_runtime_py.set_message import set_message_fields
from sensor_msgs.msg import Image, PointCloud2, PointField
from std_msgs.msg import String
from unitree_api.msg import Request
from unitree_go.msg import SportModeState
from unitree_webrtc_connect import (
    DATA_CHANNEL_TYPE,
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)

OUTPUT_TOPIC = "/go2/webrtc/sportmodestate"
REQUEST_TOPIC = "/go2/webrtc/sport/request"
POSTURE_APIS = {1001, 1002, 1003, 1004, 1005}


def create_connection(args):
    if not args.remote:
        return UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=args.ip)
    if not sys.stdin.isatty():
        raise ValueError("Run Remote mode in an interactive terminal to enter the password securely.")
    username = args.username or input("Unitree App bound account email: ").strip()
    if not username or "@" not in username:
        raise ValueError("Remote driver requires an email/password account; phone-only login is not supported.")
    password = getpass.getpass("Unitree App password (hidden, not saved): ")
    if not password:
        raise ValueError("Password cannot be empty.")
    connection = UnitreeWebRTCConnection(
        WebRTCConnectionMethod.Remote, serialNumber=args.sn,
        username=username, password=password, region=args.region, device_type="Go2",
    )
    if not connection.token:
        raise RuntimeError("Unitree cloud login failed. Check account email, password and --region.")
    return connection


async def connect_peer(connection, args):
    if args.remote:
        # Keep all normal candidates and cloud-provided TURN servers for NAT traversal.
        await asyncio.wait_for(connection.connect(), timeout=60)
        print("WebRTC Remote mode: cloud signaling / ICE / TURN", flush=True)
        return
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route_socket:
        route_socket.connect((args.ip, 9991))
        local_ip = args.local_ip or route_socket.getsockname()[0]
    with patch("aioice.ice.get_host_addresses", return_value=[local_ip]):
        await asyncio.wait_for(connection.connect(), timeout=30)
    print(f"WebRTC local ICE address: {local_ip}", flush=True)


def command_payload(request):
    api_id = request.header.identity.api_id
    if api_id == 1008:
        velocity = json.loads(request.parameter)
        if set(velocity) != {"x", "y", "z"}:
            raise ValueError("Move requires x, y and z.")
        for axis, limit in (("x", 0.35), ("y", 0.35), ("z", 1.0)):
            value = velocity[axis]
            if not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f"Invalid {axis} velocity.")
            if abs(value) > limit:
                raise ValueError(f"{axis} velocity exceeds configured keyboard range.")
        parameter = json.dumps(velocity)
    elif api_id in POSTURE_APIS:
        parameter = ""
    else:
        raise ValueError(f"Unsupported keyboard API {api_id}.")
    return {
        "header": {"identity": {"id": time.time_ns() % 2147483648, "api_id": api_id}},
        "parameter": parameter,
    }


async def bridge(args):
    connection = create_connection(args)
    node = rclpy.create_node("go2_webrtc_bridge")
    counts = {"state": 0, "image": 0, "cloud": 0, "command": 0}
    viewer = None
    moving = False
    last_command = 0.0
    try:
        state_pub = node.create_publisher(SportModeState, OUTPUT_TOPIC, 10)
        image_pub = node.create_publisher(Image, "/go2/webrtc/image", 2) if args.video else None
        cloud_pub = node.create_publisher(PointCloud2, "/go2/webrtc/points", 2) if args.lidar else None
        response_pub = node.create_publisher(String, "/go2/webrtc/sport/response", 10)
        last_received = time.monotonic()
        failure = asyncio.get_running_loop().create_future()

        def report_failure(error):
            if not failure.done():
                failure.set_result(error)

        def receive_state(envelope):
            nonlocal last_received
            try:
                message = SportModeState()
                set_message_fields(message, envelope["data"])
                state_pub.publish(message)
                counts["state"] += 1
                last_received = time.monotonic()
                if counts["state"] == 1:
                    print(f"Publishing state to {OUTPUT_TOPIC}", flush=True)
            except Exception as error:
                report_failure(error)

        def receive_cloud(envelope):
            try:
                data = envelope["data"]
                points = np.asarray(data["data"]["points"], dtype="<f4").reshape(-1, 3)
                message = PointCloud2()
                message.header.stamp = node.get_clock().now().to_msg()
                message.header.frame_id = data.get("frame_id") or "go2_webrtc_voxel"
                message.height = 1
                message.width = len(points)
                message.fields = [
                    PointField(name=axis, offset=offset, datatype=PointField.FLOAT32, count=1)
                    for axis, offset in (("x", 0), ("y", 4), ("z", 8))
                ]
                message.point_step = 12
                message.row_step = 12 * len(points)
                message.is_dense = bool(np.isfinite(points).all())
                message.data = points.tobytes()
                cloud_pub.publish(message)
                counts["cloud"] += 1
                if counts["cloud"] == 1:
                    print(f"Publishing voxel cloud: {message.width} points, frame={message.header.frame_id}", flush=True)
            except Exception as error:
                report_failure(error)

        async def receive_video(track):
            try:
                while True:
                    frame = await track.recv()
                    pixels = frame.reformat(width=640, height=360, format="rgb24").to_ndarray()
                    message = Image()
                    message.header.stamp = node.get_clock().now().to_msg()
                    message.header.frame_id = "go2_webrtc_camera"
                    message.height, message.width = pixels.shape[:2]
                    message.encoding = "rgb8"
                    message.step = message.width * 3
                    message.data = pixels.tobytes()
                    image_pub.publish(message)
                    counts["image"] += 1
                    if counts["image"] == 1:
                        print(f"Publishing image: {message.width}x{message.height}", flush=True)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                report_failure(error)

        def send_command(request):
            nonlocal moving, last_command
            try:
                payload = command_payload(request)
            except (ValueError, TypeError) as error:
                node.get_logger().warning(str(error))
                return
            if not connection.datachannel.data_channel_opened:
                node.get_logger().warning("WebRTC disconnected; command dropped.")
                return
            connection.datachannel.pub_sub.publish_without_callback(
                "rt/api/sport/request", payload, DATA_CHANNEL_TYPE["REQUEST"]
            )
            counts["command"] += 1
            last_command = time.monotonic()
            moving = request.header.identity.api_id == 1008

        await connect_peer(connection, args)
        connection.datachannel.pub_sub.subscribe("rt/lf/sportmodestate", receive_state)
        if args.video:
            connection.video.add_track_callback(receive_video)
            connection.video.switchVideoChannel(True)
        if args.lidar:
            connection.datachannel.set_decoder("native")
            await asyncio.wait_for(connection.datachannel.disableTrafficSaving(True), timeout=5)
            connection.datachannel.pub_sub.subscribe("rt/utlidar/voxel_map_compressed", receive_cloud)
        if args.control:
            # A separate ROS topic prevents duplication with the wired keyboard path.
            node.create_subscription(Request, REQUEST_TOPIC, send_command, 10)
            connection.datachannel.pub_sub.subscribe(
                "rt/api/sport/response",
                lambda envelope: response_pub.publish(String(data=json.dumps(envelope))),
            )
            print(f"Keyboard request forwarding enabled on {REQUEST_TOPIC}", flush=True)

        if args.show_video:
            viewer = subprocess.Popen([
                sys.executable, str(Path(__file__).with_name("go2_camera_viewer.py"))
            ])
        started = last_received = time.monotonic()
        next_report = started + 2
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0)
            if failure.done():
                raise failure.result()
            now = time.monotonic()
            if now >= next_report:
                print(f"Streams {counts}; state age={now - last_received:.2f}s", flush=True)
                next_report = now + 2
            if moving and now - last_command > 0.8:
                request = Request()
                request.header.identity.api_id = 1003
                send_command(request)
            if now - last_received > 10:
                raise TimeoutError("No WebRTC sport state received for 10 seconds.")
            if args.duration and now - started >= args.duration:
                break
            await asyncio.sleep(0.01)
        required = ["state"] + (["image"] if args.video else []) + (["cloud"] if args.lidar else [])
        missing = [stream for stream in required if counts[stream] == 0]
        if missing:
            raise TimeoutError(f"No samples received for {missing}")
        print(f"Published counts: {counts}", flush=True)
    finally:
        try:
            if moving and connection.pc and connection.datachannel.data_channel_opened:
                request = Request()
                request.header.identity.api_id = 1003
                send_command(request)
                await asyncio.sleep(0.1)
            await connection.disconnect()
        finally:
            if viewer is not None and viewer.poll() is None:
                viewer.terminate()
                try:
                    viewer.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    viewer.kill()
                    viewer.wait()
            node.destroy_node()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ip", help="LocalSTA: Go2 original Wi-Fi interface IP.")
    mode.add_argument("--remote", action="store_true", help="Connect over the Internet using the bound Unitree cloud account.")
    parser.add_argument("--sn", help="Remote: robot serial number from the App device information.")
    parser.add_argument("--username", help="Remote: bound account email; prompted if omitted.")
    parser.add_argument("--region", choices=("cn", "global"), default=None, help="Remote account region (default: cn).")
    parser.add_argument("--local-ip", help="PC Wi-Fi address to use for WebRTC ICE.")
    parser.add_argument("--show-video", action="store_true", help="Read and show the front camera in a PC window; Esc closes the preview.")
    parser.add_argument("--video", action="store_true", help="Bridge front camera RGB images.")
    parser.add_argument("--lidar", action="store_true", help="Bridge decoded voxel-map points.")
    parser.add_argument("--control", action="store_true", help="Forward explicit ROS keyboard requests.")
    parser.add_argument("--duration", type=float, default=0, help="Run seconds, or 0 until Ctrl+C.")
    args = parser.parse_args(argv)
    if args.remote:
        if not args.sn or not args.sn.strip():
            parser.error("--remote requires --sn from the App device information.")
        args.sn = args.sn.strip()
        if args.local_ip:
            parser.error("--local-ip is only supported with --ip.")
    elif args.sn or args.username or args.region:
        parser.error("--sn, --username and --region require --remote.")
    args.region = args.region or "cn"
    args.video = args.video or args.show_video
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("--duration must be finite and nonnegative.")
    return args


def main():
    args = parse_args()
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    try:
        asyncio.run(bridge(args))
    except KeyboardInterrupt:
        pass
    except (EOFError, ValueError, RuntimeError, TimeoutError) as error:
        print(f"Bridge stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
