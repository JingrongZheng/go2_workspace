"""Observe a sensor-only replay, save its DDDMR map and verify the assets."""
import argparse
import json
from pathlib import Path
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from sensor_msgs.msg import PointCloud2
from geometry_msgs.msg import PoseArray
from std_srvs.srv import Empty
from tf2_ros import Buffer, TransformListener


def pcd_count(path):
    with path.open("rb") as stream:
        for _ in range(30):
            line = stream.readline().decode("ascii").strip()
            if line.startswith("POINTS "):
                return int(line.split()[1])
            if line.startswith("DATA "):
                break
    raise ValueError(f"Missing PCD point count: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, required=True)
    args = parser.parse_args()
    rclpy.init(args=[])
    node = Node("go2_dddmr_mapping_session")
    buffer = Buffer()
    listener = TransformListener(buffer, node)
    stats, last, pose_counts, subscriptions = {}, {}, [], []

    def callback(message, topic):
        stats[topic] = stats.get(topic, 0) + 1
        if isinstance(message, PointCloud2):
            last[topic] = {"points": message.width * message.height, "frame": message.header.frame_id}
        else:
            pose_counts.append(len(message.poses))
            last[topic] = {"poses": len(message.poses), "frame": message.header.frame_id}

    for topic, cls in [("/dddmr/lidar_points", PointCloud2), ("/ground_cloud", PointCloud2),
                       ("/laser_cloud_sharp", PointCloud2), ("/laser_cloud_less_flat", PointCloud2),
                       ("/key_poses", PoseArray)]:
        qos = QoSProfile(depth=10)
        if topic in ("/laser_cloud_sharp", "/laser_cloud_less_flat"):
            qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        subscriptions.append(node.create_subscription(cls, topic, lambda m, t=topic: callback(m, t), qos))
    end = time.monotonic() + args.duration
    while rclpy.ok() and time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=.1)
    client = node.create_client(Empty, "/save_mapped_point_cloud")
    saved = {"service_available": client.wait_for_service(timeout_sec=5.)}
    if saved["service_available"]:
        future = client.call_async(Empty.Request())
        rclpy.spin_until_future_complete(node, future, timeout_sec=30.)
        saved["response_received"] = future.done() and future.exception() is None
    result = {"received_messages": stats, "last_messages": last,
              "maximum_key_poses": max(pose_counts, default=0), "save": saved, "tf": {}, "maps": []}
    for frame in ("base_link", "dddmr_lidar", "odom"):
        try:
            transform = buffer.lookup_transform("map", frame, rclpy.time.Time())
            p = transform.transform.translation
            result["tf"][frame] = {"xyz": [p.x, p.y, p.z]}
        except Exception as error:
            result["tf"][frame] = {"error": str(error)}
    for directory in sorted(Path("/session/maps").iterdir()):
        if not directory.is_dir():
            continue
        counts = {name: pcd_count(directory / f"{name}.pcd") for name in ("map", "ground", "poses", "edges")}
        missing = [f"{i}_{kind}.pcd" for i in range(counts["poses"]) for kind in ("feature", "surface", "ground")
                   if not (directory / "pcd" / f"{i}_{kind}.pcd").is_file()]
        result["maps"].append({"directory": str(directory.relative_to("/session")),
                               "points": counts, "missing_keyframe_files": missing})
    Path("/session/summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    node.destroy_node()
    rclpy.try_shutdown()
    if not (saved.get("response_received") and result["maps"] and result["maximum_key_poses"] >= 2):
        raise RuntimeError("No usable DDDMR map was saved; inspect session logs")
    if any(m["missing_keyframe_files"] or min(m["points"][k] for k in ("map", "ground", "poses")) <= 0 for m in result["maps"]):
        raise RuntimeError("Saved map is incomplete")
    if any("error" in value for value in result["tf"].values()):
        raise RuntimeError("Map TF chain is incomplete")


if __name__ == "__main__":
    main()
