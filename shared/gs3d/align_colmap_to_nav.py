#!/usr/bin/env python3
"""Align COLMAP sparse reconstruction to DDDMR nav map (Sim3 via /mcl_pose) or D435i metric depth,
and optionally seed points3D with subsampled aligned D435i depth points.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image


def qvec2rotmat(qvec):
    w, x, y, z = qvec
    return np.array([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * z * w, 2 * x * z + 2 * y * w],
        [2 * x * y + 2 * z * w, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * x * w],
        [2 * x * z - 2 * y * w, 2 * y * z + 2 * x * w, 1 - 2 * x * x - 2 * y * y],
    ], dtype=np.float64)


def rotmat2qvec(R):
    # Shepperd's method -> [w, x, y, z]
    trace = np.trace(R)
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=np.float64)
    return q / np.linalg.norm(q)


def read_colmap_txt(sparse_dir: Path):
    cameras = {}
    for line in (sparse_dir / "cameras.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        cid = int(parts[0])
        cameras[cid] = {
            "id": cid,
            "model": parts[1],
            "width": int(parts[2]),
            "height": int(parts[3]),
            "params": [float(v) for v in parts[4:]],
        }

    images = {}
    img_lines = [l for l in (sparse_dir / "images.txt").read_text().splitlines() if l and not l.startswith("#")]
    for i in range(0, len(img_lines), 2):
        parts = img_lines[i].split()
        iid = int(parts[0])
        qvec = np.array([float(v) for v in parts[1:5]], dtype=np.float64)
        tvec = np.array([float(v) for v in parts[5:8]], dtype=np.float64)
        cid = int(parts[8])
        name = parts[9]
        images[iid] = {
            "id": iid,
            "qvec": qvec,
            "tvec": tvec,
            "camera_id": cid,
            "name": name,
            "points2d_line": img_lines[i + 1] if i + 1 < len(img_lines) else "",
        }

    points = []
    for line in (sparse_dir / "points3D.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        points.append({
            "id": int(parts[0]),
            "xyz": np.array([float(parts[1]), float(parts[2]), float(parts[3])], dtype=np.float64),
            "rgb": [int(parts[4]), int(parts[5]), int(parts[6])],
            "error": float(parts[7]),
            "track": " ".join(parts[8:]),
        })
    return cameras, images, points


def umeyama_sim3(src: np.ndarray, dst: np.ndarray):
    """Find scale s, rotation R, translation t minimizing ||dst - (s * R @ src + t)||^2."""
    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    cs = src - mu_s
    cd = dst - mu_d
    var_s = np.mean(np.sum(cs ** 2, axis=1))
    cov = (cd.T @ cs) / len(src)
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1.0
    R = U @ S @ Vt
    scale = float(np.trace(np.diag(D) @ S) / max(var_s, 1e-12))
    t = mu_d - scale * (R @ mu_s)
    return scale, R, t


def ransac_sim3(src: np.ndarray, dst: np.ndarray, threshold_m: float = 0.25, iters: int = 500):
    rng = np.random.default_rng(42)
    n = len(src)
    best_inliers = np.ones(n, dtype=bool)
    best_count = -1
    for _ in range(iters):
        idx = rng.choice(n, size=3, replace=False)
        s, R, t = umeyama_sim3(src[idx], dst[idx])
        if not (0.05 < s < 100.0):
            continue
        pred = (s * (src @ R.T)) + t
        err = np.linalg.norm(pred - dst, axis=1)
        inliers = err < threshold_m
        cnt = int(inliers.sum())
        if cnt > best_count:
            best_count = cnt
            best_inliers = inliers
    if best_count < 4:
        best_inliers = np.ones(n, dtype=bool)
    s, R, t = umeyama_sim3(src[best_inliers], dst[best_inliers])
    pred = (s * (src[best_inliers] @ R.T)) + t
    rmse = float(np.sqrt(np.mean(np.sum((pred - dst[best_inliers]) ** 2, axis=1))))
    return s, R, t, rmse, int(best_inliers.sum())


def estimate_depth_scale(images, points, dataset_dir: Path, depth_scale: float, cameras):
    """Fallback: estimate COLMAP->meter scale from median ratio of D435i raw depth to COLMAP depth."""
    pts_by_id = {p["id"]: p["xyz"] for p in points}
    ratios = []
    for img in list(images.values())[::max(1, len(images) // 40)]:
        stem = Path(img["name"]).stem
        dep_path = dataset_dir / "depth" / f"{stem}.png"
        if not dep_path.exists():
            continue
        depth_m = np.asarray(Image.open(dep_path), dtype=np.float64) * depth_scale
        h, w = depth_m.shape
        R = qvec2rotmat(img["qvec"])
        t = img["tvec"]
        tokens = img["points2d_line"].split()
        for k in range(0, len(tokens) - 2, 3):
            pid = int(tokens[k + 2])
            if pid == -1 or pid not in pts_by_id:
                continue
            u, v = int(round(float(tokens[k]))), int(round(float(tokens[k + 1])))
            if not (0 <= u < w and 0 <= v < h):
                continue
            z_sensor = depth_m[v, u]
            if not (0.4 <= z_sensor <= 4.5):
                continue
            p_cam = R @ pts_by_id[pid] + t
            if p_cam[2] > 0.05:
                ratios.append(z_sensor / p_cam[2])
    if len(ratios) < 20:
        return 1.0, len(ratios)
    return float(np.median(ratios)), len(ratios)


def backproject_depth_seed(images, cameras, dataset_dir: Path, depth_scale: float, max_points: int = 80000):
    """Backproject aligned D435i 16-bit depth into aligned metric world coordinates to seed 3DGS."""
    img_list = list(images.values())
    if not img_list:
        return []
    per_frame = max(200, max_points // len(img_list))
    rng = np.random.default_rng(123)
    seed_pts = []
    for img in img_list:
        stem = Path(img["name"]).stem
        dep_path = dataset_dir / "depth" / f"{stem}.png"
        rgb_path = dataset_dir / "images" / Path(img["name"]).name
        if not dep_path.exists() or not rgb_path.exists():
            continue
        depth_m = np.asarray(Image.open(dep_path), dtype=np.float64) * depth_scale
        rgb = np.asarray(Image.open(rgb_path).convert("RGB"), dtype=np.uint8)
        cam = cameras[img["camera_id"]]
        fx, fy, cx, cy = cam["params"][:4]
        valid_v, valid_u = np.where((depth_m >= 0.35) & (depth_m <= 4.5))
        if len(valid_u) == 0:
            continue
        take = min(per_frame, len(valid_u))
        sel = rng.choice(len(valid_u), size=take, replace=False)
        u = valid_u[sel].astype(np.float64)
        v = valid_v[sel].astype(np.float64)
        z = depth_m[valid_v[sel], valid_u[sel]]
        x = (u - cx) * z / fx
        y = (v - cy) * z / fy
        pts_cam = np.stack([x, y, z], axis=1)
        R_cw = qvec2rotmat(img["qvec"])
        t_cw = img["tvec"]
        pts_w = (pts_cam - t_cw) @ R_cw  # R_cw^T (p_cam - t_cw)
        cols = rgb[valid_v[sel], valid_u[sel]]
        for pw, c in zip(pts_w, cols):
            seed_pts.append((pw, [int(c[0]), int(c[1]), int(c[2])]))
    return seed_pts


def write_colmap_txt(out_dir: Path, cameras, images, points):
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "cameras.txt").open("w") as f:
        f.write("# CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        for c in cameras.values():
            params = " ".join(f"{v:.8f}" for v in c["params"])
            f.write(f"{c['id']} {c['model']} {c['width']} {c['height']} {params}\n")

    with (out_dir / "images.txt").open("w") as f:
        f.write("# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        for im in images.values():
            q = " ".join(f"{v:.10f}" for v in im["qvec"])
            t = " ".join(f"{v:.10f}" for v in im["tvec"])
            f.write(f"{im['id']} {q} {t} {im['camera_id']} {im['name']}\n")
            f.write(f"{im['points2d_line']}\n")

    with (out_dir / "points3D.txt").open("w") as f:
        f.write("# POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[]\n")
        for pt in points:
            x, y, z = pt["xyz"]
            r, g, b = pt["rgb"]
            f.write(f"{pt['id']} {x:.6f} {y:.6f} {z:.6f} {r} {g} {b} {pt['error']:.4f} {pt['track']}\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, required=True, help="RGB-D dataset directory")
    p.add_argument("--sparse-txt", type=Path, required=True, help="COLMAP sparse TXT directory")
    p.add_argument("--output-txt", type=Path, required=True, help="Aligned COLMAP sparse TXT output directory")
    p.add_argument("--seed-depth-points", type=int, default=80000,
                   help="Max D435i depth backprojected seed points to append (0 to disable)")
    args = p.parse_args()

    intr = json.loads((args.dataset / "intrinsics.json").read_text())
    depth_scale = float(intr.get("depth_scale", 0.001))
    cameras, images, points = read_colmap_txt(args.sparse_txt)

    mcl_by_name = {}
    frames_file = args.dataset / "frames.jsonl"
    if frames_file.exists():
        for line in frames_file.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("mcl_pose_map") is not None:
                mcl_by_name[Path(rec["image"]).name] = np.array(rec["mcl_pose_map"][:3], dtype=np.float64)

    src_centers = []
    dst_centers = []
    for im in images.values():
        name = Path(im["name"]).name
        if name in mcl_by_name:
            R_cw = qvec2rotmat(im["qvec"])
            c_colmap = -R_cw.T @ im["tvec"]
            src_centers.append(c_colmap)
            dst_centers.append(mcl_by_name[name])

    if len(src_centers) >= 10:
        src_arr = np.asarray(src_centers)
        dst_arr = np.asarray(dst_centers)
        scale, R_align, t_align, rmse_m, inliers = ransac_sim3(src_arr, dst_arr)
        mode = "mcl_sim3"
        print(
            f"[ALIGN] Sim(3) aligned to DDDMR nav map: scale={scale:.5f}, "
            f"inliers={inliers}/{len(src_arr)}, rmse={rmse_m:.3f} m",
            flush=True,
        )
    else:
        scale, n_pairs = estimate_depth_scale(images, points, args.dataset, depth_scale, cameras)
        R_align = np.eye(3, dtype=np.float64)
        t_align = np.zeros(3, dtype=np.float64)
        rmse_m = None
        inliers = n_pairs
        mode = "d435i_depth_scale"
        print(
            f"[ALIGN] No/few /mcl_pose ({len(src_centers)} < 10); applied D435i metric depth scale="
            f"{scale:.5f} from {n_pairs} correspondences.",
            flush=True,
        )

    # Apply X_new = scale * R_align @ X_old + t_align to all cameras and 3D points.
    # For camera: R_new = R_old @ R_align^T, C_new = scale * R_align @ C_old + t_align, t_new = -R_new @ C_new
    for im in images.values():
        R_old = qvec2rotmat(im["qvec"])
        C_old = -R_old.T @ im["tvec"]
        R_new = R_old @ R_align.T
        C_new = scale * (R_align @ C_old) + t_align
        im["qvec"] = rotmat2qvec(R_new)
        im["tvec"] = -R_new @ C_new

    for pt in points:
        pt["xyz"] = scale * (R_align @ pt["xyz"]) + t_align

    added_seed = 0
    if args.seed_depth_points > 0:
        seed_pts = backproject_depth_seed(images, cameras, args.dataset, depth_scale, args.seed_depth_points)
        next_id = max((pt["id"] for pt in points), default=0) + 1
        for xyz, rgb in seed_pts:
            points.append({"id": next_id, "xyz": xyz, "rgb": rgb, "error": 0.0, "track": ""})
            next_id += 1
        added_seed = len(seed_pts)
        print(f"[ALIGN] Added {added_seed} metric D435i depth seed points (total={len(points)})", flush=True)

    write_colmap_txt(args.output_txt, cameras, images, points)

    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = scale * R_align
    T[:3, 3] = t_align
    meta = {
        "mode": mode,
        "scale": scale,
        "R": R_align.tolist(),
        "t": t_align.tolist(),
        "T_nav_from_colmap": T.tolist(),
        "rmse_m": rmse_m,
        "inliers": inliers,
        "registered_images": len(images),
        "added_depth_seed_points": added_seed,
    }
    (args.output_txt.parent / "alignment.json").write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    main()
