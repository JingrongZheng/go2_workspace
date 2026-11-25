"""Test only known telemetry subscriptions on a Go2 LocalSTA session."""
import argparse
import asyncio
import ipaddress
import json
import os
import socket
import struct
import time
from unittest.mock import patch

from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod

TOPICS = (
    "rt/lf/sportmodestate",
    "rt/utlidar/lidar_state",
    "rt/utlidar/voxel_map_compressed",
    "rt/utlidar/cloud",
    "rt/utlidar/imu",
)


def describe(envelope):
    data = envelope.get("data")
    result = {"envelope_keys": sorted(envelope), "data_type": type(data).__name__}
    if isinstance(data, dict):
        result["data_keys"] = sorted(data)
        if isinstance(data.get("header"), dict):
            result["header"] = {k: v for k, v in data["header"].items() if k in ("stamp", "frame_id")}
        if isinstance(data.get("fields"), list):
            result["fields"] = [f.get("name") for f in data["fields"] if isinstance(f, dict)]
        for name in ("frame_id", "stamp", "width", "height", "point_step"):
            if isinstance(data.get(name), (str, int, float)):
                result[name] = data[name]
        decoded = data.get("data")
        if isinstance(decoded, (bytes, bytearray, list, str)):
            result["payload_length"] = len(decoded)
        elif isinstance(decoded, dict):
            result["decoded_keys"] = sorted(decoded)
    return result


async def probe(ip, duration, full_stream):
    os.environ["NO_PROXY"] = ",".join(filter(None, (os.environ.get("NO_PROXY"), ip)))
    os.environ["no_proxy"] = ",".join(filter(None, (os.environ.get("no_proxy"), ip)))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((ip, 9991))
        local_ip = sock.getsockname()[0]
    print(f"target={ip} local_ice={local_ip}", flush=True)
    connection = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=ip)
    received = {topic: {"count": 0} for topic in TOPICS}

    packets = {topic: {"count": 0} for topic in TOPICS}

    def inspect_wire(message):
        try:
            binary_length = 0
            if isinstance(message, str):
                envelope = json.loads(message)
            else:
                if len(message) < 4:
                    return
                marker, version = struct.unpack_from("<HH", message)
                if (marker, version) == (2, 0):
                    if len(message) < 12:
                        return
                    length, = struct.unpack_from("<I", message, 4)
                    offset = 12
                else:
                    length, offset = marker, 4
                if not 0 < length <= len(message) - offset:
                    return
                envelope = json.loads(message[offset:offset + length])
                binary_length = len(message) - offset - length
            stats = packets.get(envelope.get("topic"))
            if stats is not None:
                if stats["count"] == 0:
                    stats.update(describe(envelope), kind=envelope.get("type"), binary_length=binary_length)
                stats["count"] += 1
        except (UnicodeDecodeError, ValueError, TypeError, AttributeError):
            pass

    def callback(topic):
        def receive(message):
            stats = received[topic]
            now = time.monotonic()
            if stats["count"] == 0:
                stats["first"] = now
                stats["sample"] = describe(message)
            stats["count"] += 1
            stats["last"] = now
        return receive

    try:
        with patch("aioice.ice.get_host_addresses", return_value=[local_ip]):
            await asyncio.wait_for(connection.connect(), timeout=28)
        connection.datachannel.set_decoder("native")
        connection.datachannel.channel.on("message", inspect_wire)
        if full_stream:
            enabled = await asyncio.wait_for(connection.datachannel.disableTrafficSaving(True), timeout=5)
            print(f"session_full_stream_ack={enabled}", flush=True)
        for topic in TOPICS:
            connection.datachannel.pub_sub.subscribe(topic, callback(topic))
        await asyncio.sleep(duration)
        for stats in received.values():
            start = stats.pop("first", None)
            end = stats.pop("last", None)
            if start is not None and end > start:
                stats["hz"] = round((stats["count"] - 1) / (end - start), 2)
        print(json.dumps({"seconds": duration, "topics": received, "wire_packets": packets}, ensure_ascii=False, default=str), flush=True)
    finally:
        await asyncio.wait_for(connection.disconnect(), timeout=6)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ip", type=ipaddress.IPv4Address)
    parser.add_argument("--duration", type=int, default=12, choices=range(1, 31))
    parser.add_argument("--full-stream", action="store_true", help="Disable WebRTC session traffic saving")
    args = parser.parse_args()
    asyncio.run(probe(str(args.ip), args.duration, args.full_stream))
