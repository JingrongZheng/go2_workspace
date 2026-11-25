"""Estimate radar IMU rotation into chassis IMU axes from a paired gyro recording."""
import argparse
import json
from pathlib import Path

import numpy as np


def read_samples(path):
    groups = {"lidar": [], "body": []}
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if row.get("stream") in groups:
            groups[row["stream"]].append(row)
    if min(map(len, groups.values())) < 40:
        raise ValueError("Both IMUs need at least 40 samples")
    origin = min(row["dock_receive_ns"] for values in groups.values() for row in values)
    output = []
    for name, values in groups.items():
        t = np.array([row["dock_receive_ns"] - origin for row in values], dtype=np.int64)
        if name == "lidar":
            source = np.array([row["source_stamp_or_tick"] - origin for row in values], dtype=np.int64)
            t = source + int(np.median(t - source))
        gyro = np.array([row["gyro"] for row in values])
        if np.any(np.diff(t) <= 0) or not np.isfinite(gyro).all():
            raise ValueError(f"{name} samples contain invalid values or non-increasing stamps")
        output.append((t * 1e-9, gyro))
    return output


def demean_using_initial_rest(t, gyro):
    resting = gyro[t <= t[0] + 1]
    if len(resting) < 10 or np.quantile(np.linalg.norm(resting - np.median(resting, axis=0), axis=1), .9) > .06:
        raise ValueError("Keep the robot still for the first second of the capture")
    return gyro - np.median(resting, axis=0)


def fit(lidar_t, lidar_gyro, body_t, body_gyro):
    lidar = lidar_gyro - np.median(lidar_gyro, axis=0)
    body = body_gyro - np.median(body_gyro, axis=0)
    active = ((np.linalg.norm(body, axis=1) > .08)
              & (body_t > lidar_t[0] + .25) & (body_t < lidar_t[-1] - .25))
    t, target = body_t[active], body[active]
    if len(t) < 15:
        raise ValueError("Insufficient rotation. Capture gentle pitch and roll in two directions")
    train = np.arange(len(t)) % 4 != 0
    singular = np.linalg.svd(target[train], compute_uv=False)
    if singular[1] < singular[0] * .15:
        raise ValueError("Only one clear rotation axis. Capture rotation around a second axis")
    candidates = []
    for lag in np.linspace(-.2, .2, 81):
        src = np.column_stack([np.interp(t + lag, lidar_t, column) for column in lidar.T])
        u, _, vt = np.linalg.svd((src[train] - src[train].mean(0)).T @ (target[train] - target[train].mean(0)))
        handedness = np.sign(np.linalg.det(vt.T @ u.T))
        rotation = vt.T @ np.diag([1, 1, handedness]) @ u.T
        bias = target[train].mean(0) - rotation @ src[train].mean(0)
        error = src @ rotation.T + bias - target
        candidates.append((np.mean(error[train] ** 2), lag, rotation, error))
    _, lag, rotation, error = min(candidates, key=lambda row: row[0])
    holdout = error[~train]
    error_rms = float(np.sqrt(np.mean(np.sum(holdout ** 2, axis=1))))
    signal_rms = float(np.sqrt(np.mean(np.sum(target[~train] ** 2, axis=1))))
    return {"convention": "omega_chassis_imu = R @ omega_radar_imu",
            "rotation_matrix": rotation.tolist(), "candidate_alignment_lag_s": float(lag),
            "moving_pairs": len(t), "second_to_first_axis_strength": float(singular[1]/singular[0]),
            "held_out_gyro_error_rms_rad_s": error_rms, "held_out_error_to_signal": error_rms/signal_rms,
            "status": "candidate rotation only; confirm error, playback and geometry before use"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    try:
        (lt, lg), (bt, bg) = read_samples(args.capture)
        print(json.dumps(fit(lt, lg, bt, bg), indent=2))
    except ValueError as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
