"""Verify timing and field preservation in the automatic-alignment ROS bag."""
import json
import statistics
import struct
import sys
from collections import defaultdict

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

reader = rosbag2_py.SequentialReader()
reader.open(rosbag2_py.StorageOptions(uri=sys.argv[1], storage_id="sqlite3"),
            rosbag2_py.ConverterOptions("", ""))
types = {item.name: get_message(item.type) for item in reader.get_all_topics_and_types()}
ages = defaultdict(list)
timestamps = defaultdict(list)
cloud_spans = []
while reader.has_next():
    topic, data, received_ns = reader.read_next()
    msg = deserialize_message(data, types[topic])
    stamp = msg.header.stamp
    stamp_ns = stamp.sec * 1_000_000_000 + stamp.nanosec
    ages[topic].append((received_ns - stamp_ns) / 1e6)
    timestamps[topic].append(stamp_ns)
    if topic.endswith("/cloud"):
        fields = {f.name: f for f in msg.fields}
        assert fields["time"].datatype == 7 and fields["ring"].datatype == 4
        fmt = ">f" if msg.is_bigendian else "<f"
        offset = fields["time"].offset
        first = struct.unpack_from(fmt, msg.data, offset)[0]
        last = struct.unpack_from(fmt, msg.data, (msg.width-1)*msg.point_step+offset)[0]
        cloud_spans.append((last-first)*1e3)
report = {}
for topic in ("/go2/relay/cloud", "/go2/relay/imu"):
    seq = timestamps[topic]
    assert len(seq) > 10
    assert all(b > a for a, b in zip(seq, seq[1:]))
    report[topic] = {
        "count": len(seq),
        "header_rate_hz": (len(seq)-1)*1e9/(seq[-1]-seq[0]),
        "receive_minus_header_median_ms": statistics.median(ages[topic]),
        "receive_minus_header_p95_ms": statistics.quantiles(ages[topic], n=20)[-1],
        "receive_minus_header_max_ms": max(ages[topic]),
    }
    assert -25 < report[topic]["receive_minus_header_median_ms"] < 150
    assert report[topic]["receive_minus_header_max_ms"] < 750
report["cloud_per_point_span_median_ms"] = statistics.median(cloud_spans)
assert 50 < report["cloud_per_point_span_median_ms"] < 75
print(json.dumps(report, indent=2))
