#!/usr/bin/env python3
"""Interactive browser 3DGS viewer for standard .ply files using viser."""
import argparse
from pathlib import Path
import time

import numpy as np
from plyfile import PlyData
import viser


def load_ply_splats(ply_path: Path):
    ply = PlyData.read(str(ply_path))
    v = ply["vertex"]
    centers = np.stack([v["x"], v["y"], v["z"]], axis=-1).astype(np.float32)
    opacities = (1.0 / (1.0 + np.exp(-np.asarray(v["opacity"], dtype=np.float32))))[:, None]
    scales = np.exp(np.stack([v["scale_0"], v["scale_1"], v["scale_2"]], axis=-1).astype(np.float32))
    quats = np.stack([v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], axis=-1).astype(np.float32)
    quats /= np.linalg.norm(quats, axis=-1, keepdims=True) + 1e-8
    rgbs = np.clip(
        np.stack([v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], axis=-1).astype(np.float32) * 0.28209479177387814 + 0.5,
        0.0, 1.0,
    )
    # Build 3x3 covariances R @ diag(s^2) @ R^T for viser
    w, x, y, z = quats[:, 0], quats[:, 1], quats[:, 2], quats[:, 3]
    R = np.stack([
        1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
        2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
        2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
    ], axis=-1).reshape(-1, 3, 3)
    M = R * scales[:, None, :]
    covs = M @ np.swapaxes(M, 1, 2)
    return centers, covs, rgbs, opacities


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ply", type=Path)
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()

    print(f"[VIEW] Loading {args.ply} ...", flush=True)
    centers, covs, rgbs, opacities = load_ply_splats(args.ply)
    print(f"[VIEW] Loaded {len(centers):,} Gaussians. Open http://localhost:{args.port} in your browser.", flush=True)

    server = viser.ViserServer(host="0.0.0.0", port=args.port)
    server.scene.add_gaussian_splats(
        "/lab_3dgs",
        centers=centers,
        covariances=covs,
        rgbs=rgbs,
        opacities=opacities,
    )
    server.scene.add_grid("/grid", width=20.0, height=20.0, position=(0.0, 0.0, -0.32))
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
