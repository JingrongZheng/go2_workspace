"""Check candidate LiDAR IMU rotations against simultaneous body IMU gravity."""
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def angle_deg(a, b):
    return float(np.rad2deg(np.arccos(np.clip(
        np.dot(a, b) / np.linalg.norm(a) / np.linalg.norm(b), -1.0, 1.0))))


folder = Path(__file__).parent
samples = [json.loads(line) for line in (folder / "imu-pair.jsonl").read_text().splitlines()]
fit = json.loads((folder.parent / "EXP-0018/cloud-geometry-summary.json").read_text())["same_point_fit"]
reported_rotation = Rotation.from_euler("xyz", fit["rpy_xyz_rad"])
result = {"measurements": {}}
accels = {}
for kind in ("lidar", "body"):
    rows = [m for m in samples if m.get("stream") == kind]
    a = np.array([m["accel"] for m in rows])
    g = np.array([m["gyro"] for m in rows])
    accels[kind] = np.median(a, axis=0)
    report = {
        "samples": len(rows),
        "median_accel_m_s2": accels[kind].tolist(),
        "median_accel_norm_m_s2": float(np.median(np.linalg.norm(a, axis=1))),
        "gyro_norm_p95_rad_s": float(np.quantile(np.linalg.norm(g, axis=1), .95)),
    }
    if kind == "lidar":
        delta = np.array([(m["dock_receive_ns"]-m["source_stamp_or_tick"])/1e9 for m in rows])
        report["dock_clock_minus_header_median_s"] = float(np.median(delta))
    result["measurements"][kind] = report
candidates = {
    "old_urdf_and_parallel_lidar_imu": Rotation.from_euler("y", 2.8782),
    "firmware_cloud_to_base_and_parallel_lidar_imu": reported_rotation,
    "cmu_l1_accel_rotation_only_without_bias": Rotation.from_euler("xyz", [180, -15.1, 0], degrees=True),
    "identity": Rotation.identity(),
}
result["angle_to_body_accel_deg"] = {name: angle_deg(rot.apply(accels["lidar"]), accels["body"])
                                    for name, rot in candidates.items()}
result["cloud_to_firmware_base"] = {
    "convention": "p_base = R @ p_cloud + t",
    "source": "/utlidar/cloud, /utlidar/cloud_base",
    "translation_m": fit["translation_m"],
    "rotation_matrix": reported_rotation.as_matrix().tolist(),
    "rpy_deg": reported_rotation.as_euler("xyz", degrees=True).tolist(),
    "quaternion_xyzw": reported_rotation.as_quat().tolist(),
    "fit_median_error_m": fit["median_pair_error_m"],
    "matched_points": fit["matched_points"],
    "status": "observed topic transform; LiDAR-to-IMU rotation remains undetermined",
    "rotation_after_removing_nominal_urdf_pitch_rpy_deg": (
        Rotation.from_euler("y", 2.8782).inv() * reported_rotation).as_euler("xyz", degrees=True).tolist(),
}
print(json.dumps(result, indent=2))
