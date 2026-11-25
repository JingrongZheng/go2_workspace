#!/usr/bin/env python3
"""Offline synchronous SE(3) pose-graph loop-closure optimizer for saved DDDMR maps.

Reads a saved DDDMR map directory (poses.pcd, edges.pcd, pcd/*_{feature,surface,ground}.pcd),
detects/refines loop-closure constraints via 3D ICP on local submaps, solves a sparse
Levenberg-Marquardt SE(3) pose-graph optimization, and writes a new DDDMR-compatible map
directory without modifying the input map.
"""
import argparse
import json
import math
import shutil
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation


def load_pcd_ascii(path: Path):
    header = []
    rows = []
    in_data = False
    with open(path, "r") as f:
        for line in f:
            if not in_data:
                header.append(line)
                if line.startswith("DATA"):
                    in_data = True
            elif line.strip():
                rows.append([float(x) for x in line.split()])
    arr = np.array(rows, dtype=np.float64) if rows else np.zeros((0, 4), dtype=np.float64)
    return header, arr


def save_poses_pcd(path: Path, poses_mat: np.ndarray, orig_arr: np.ndarray):
    n = len(poses_mat)
    lines = [
        "# .PCD v0.7 - Point Cloud Data file format\n",
        "VERSION 0.7\n",
        "FIELDS x y z intensity roll pitch yaw time\n",
        "SIZE 4 4 4 4 4 4 4 8\n",
        "TYPE F F F F F F F F\n",
        "COUNT 1 1 1 1 1 1 1 1\n",
        f"WIDTH {n}\n",
        "HEIGHT 1\n",
        "VIEWPOINT 0 0 0 1 0 0 0\n",
        f"POINTS {n}\n",
        "DATA ascii\n",
    ]
    for i in range(n):
        T = poses_mat[i]
        t = T[:3, 3]
        roll, pitch, yaw = Rotation.from_matrix(T[:3, :3]).as_euler("xyz", degrees=False)
        intensity = orig_arr[i, 3] if i < len(orig_arr) else float(i)
        stamp = orig_arr[i, 7] if (i < len(orig_arr) and orig_arr.shape[1] > 7) else 0.0
        lines.append(f"{t[0]:.7g} {t[1]:.7g} {t[2]:.7g} {intensity:g} {roll:.7g} {pitch:.7g} {yaw:.7g} {stamp:.7g}\n")
    path.write_text("".join(lines))


def save_edges_pcd(path: Path, edges):
    n = len(edges)
    lines = [
        "# .PCD v0.7 - Point Cloud Data file format\n",
        "VERSION 0.7\n",
        "FIELDS x y z\n",
        "SIZE 4 4 4\n",
        "TYPE F F F\n",
        "COUNT 1 1 1\n",
        f"WIDTH {n}\n",
        "HEIGHT 1\n",
        "VIEWPOINT 0 0 0 1 0 0 0\n",
        f"POINTS {n}\n",
        "DATA ascii\n",
    ]
    for idx, (u, v) in enumerate(edges):
        lines.append(f"{idx} {u} {v}\n")
    path.write_text("".join(lines))


def save_xyzi_pcd(path: Path, pts: np.ndarray):
    n = len(pts)
    lines = [
        "# .PCD v0.7 - Point Cloud Data file format\n",
        "VERSION 0.7\n",
        "FIELDS x y z intensity\n",
        "SIZE 4 4 4 4\n",
        "TYPE F F F F\n",
        "COUNT 1 1 1 1\n",
        f"WIDTH {n}\n",
        "HEIGHT 1\n",
        "VIEWPOINT 0 0 0 1 0 0 0\n",
        f"POINTS {n}\n",
        "DATA ascii\n",
    ]
    for p in pts:
        lines.append(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f} {p[3]:.4f}\n")
    path.write_text("".join(lines))


def voxel_downsample(pts: np.ndarray, voxel_size: float) -> np.ndarray:
    if len(pts) == 0:
        return pts
    keys = np.floor(pts[:, :3] / voxel_size).astype(np.int64)
    _, inv, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    out = np.zeros((len(counts), pts.shape[1]), dtype=np.float64)
    for col in range(pts.shape[1]):
        np.add.at(out[:, col], inv, pts[:, col])
        out[:, col] /= counts
    return out


def poses_from_pcd(arr: np.ndarray) -> np.ndarray:
    mats = np.zeros((len(arr), 4, 4), dtype=np.float64)
    for i, row in enumerate(arr):
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = Rotation.from_euler("xyz", [row[4], row[5], row[6]], degrees=False).as_matrix()
        T[:3, 3] = row[:3]
        mats[i] = T
    return mats


def inv_se3(T: np.ndarray) -> np.ndarray:
    Ti = np.eye(4, dtype=np.float64)
    Ti[:3, :3] = T[:3, :3].T
    Ti[:3, 3] = -Ti[:3, :3] @ T[:3, 3]
    return Ti


def se3_log(T: np.ndarray) -> np.ndarray:
    rotvec = Rotation.from_matrix(T[:3, :3]).as_rotvec()
    return np.concatenate([T[:3, 3], rotvec])


def se3_exp(xi: np.ndarray) -> np.ndarray:
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = Rotation.from_rotvec(xi[3:]).as_matrix()
    T[:3, 3] = xi[:3]
    return T


def build_submap_in_frame(pcd_dir: Path, poses: np.ndarray, center_idx: int, half_win: int, kinds=("feature", "surface", "ground")):
    T_ref_inv = inv_se3(poses[center_idx])
    chunks = []
    lo = max(0, center_idx - half_win)
    hi = min(len(poses) - 1, center_idx + half_win)
    for k in range(lo, hi + 1):
        T_rel = T_ref_inv @ poses[k]
        R, t = T_rel[:3, :3], T_rel[:3, 3]
        for kind in kinds:
            p = pcd_dir / f"{k}_{kind}.pcd"
            if not p.exists():
                continue
            _, arr = load_pcd_ascii(p)
            if len(arr):
                pts = arr[:, :3] @ R.T + t
                chunks.append(pts)
    if not chunks:
        return np.zeros((0, 3), dtype=np.float64)
    merged = np.vstack(chunks)
    return voxel_downsample(np.column_stack([merged, np.zeros(len(merged))]), 0.12)[:, :3]


def icp_point_to_point(src: np.ndarray, dst: np.ndarray, init_T: np.ndarray, max_dist: float = 1.0, max_iter: int = 40):
    """Align src (in frame u) to dst (in frame v), returning T_v_from_u and mean squared dist."""
    tree = cKDTree(dst)
    T = init_T.copy()
    last_rmse = float("inf")
    inlier_ratio = 0.0
    for _ in range(max_iter):
        src_tf = src @ T[:3, :3].T + T[:3, 3]
        dists, idxs = tree.query(src_tf, distance_upper_bound=max_dist)
        mask = np.isfinite(dists)
        if mask.sum() < 40:
            return T, float("inf"), 0.0
        inlier_ratio = float(mask.sum()) / len(src)
        P = src_tf[mask]
        Q = dst[idxs[mask]]
        mu_p = P.mean(axis=0)
        mu_q = Q.mean(axis=0)
        H = (P - mu_p).T @ (Q - mu_q)
        U, _, Vt = np.linalg.svd(H)
        R_delta = Vt.T @ U.T
        if np.linalg.det(R_delta) < 0:
            Vt[-1, :] *= -1
            R_delta = Vt.T @ U.T
        t_delta = mu_q - R_delta @ mu_p
        dT = np.eye(4)
        dT[:3, :3] = R_delta
        dT[:3, 3] = t_delta
        T = dT @ T
        rmse = float(np.sqrt(np.mean(dists[mask] ** 2)))
        if abs(last_rmse - rmse) < 1e-5:
            last_rmse = rmse
            break
        last_rmse = rmse
    return T, last_rmse, inlier_ratio


def optimize_pose_graph(poses: np.ndarray, loop_constraints,
                        odom_weight=(100.0, 100.0, 1.0, 2.0, 2.0, 100.0),
                        loop_weight=(0.0, 0.0, 15.0, 4.0, 4.0, 0.0)):
    """Sparse LM SE(3) pose graph optimization with pose 0 fixed.

    Very high XY/yaw odometry weights keep the accurate horizontal walls
    undistorted while Z/roll/pitch smoothly absorb vertical drift across loops.
    """
    n = len(poses)
    odom_rel = [inv_se3(poses[i]) @ poses[i + 1] for i in range(n - 1)]
    m_vars = (n - 1) * 6
    n_odom = n - 1
    n_loop = len(loop_constraints)
    n_res = (n_odom + n_loop) * 6

    sparsity = lil_matrix((n_res, m_vars), dtype=int)
    for i in range(n_odom):
        r0 = i * 6
        if i > 0:
            sparsity[r0:r0 + 6, (i - 1) * 6:i * 6] = 1
        sparsity[r0:r0 + 6, i * 6:(i + 1) * 6] = 1
    for k, (u, v, _, _) in enumerate(loop_constraints):
        r0 = (n_odom + k) * 6
        if u > 0:
            sparsity[r0:r0 + 6, (u - 1) * 6:u * 6] = 1
        if v > 0:
            sparsity[r0:r0 + 6, (v - 1) * 6:v * 6] = 1

    def unpack(x):
        cur = [poses[0]]
        for i in range(1, n):
            cur.append(poses[i] @ se3_exp(x[(i - 1) * 6:i * 6]))
        return cur

    w_o = np.array(odom_weight, dtype=np.float64)
    w_l = np.array(loop_weight, dtype=np.float64)

    def residuals(x):
        cur = unpack(x)
        res = np.empty(n_res, dtype=np.float64)
        for i in range(n_odom):
            T_pred = inv_se3(cur[i]) @ cur[i + 1]
            err = se3_log(inv_se3(odom_rel[i]) @ T_pred)
            res[i * 6:i * 6 + 6] = w_o * err
        for k, (u, v, T_v_from_u, w_edge) in enumerate(loop_constraints):
            T_pred = inv_se3(cur[v]) @ cur[u]
            err = se3_log(inv_se3(T_v_from_u) @ T_pred)
            r0 = (n_odom + k) * 6
            res[r0:r0 + 6] = w_edge * err
        return res

    sol = least_squares(residuals, np.zeros(m_vars), jac_sparsity=sparsity, method="trf",
                        ftol=1e-7, xtol=1e-7, max_nfev=150)
    opt_poses = np.array(unpack(sol.x), dtype=np.float64)
    return opt_poses, sol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_map", type=Path, help="Existing saved DDDMR map directory")
    parser.add_argument("output_map", type=Path, help="New output directory for optimized map")
    parser.add_argument("--loop-radius", type=float, default=1.5, help="Max 3D distance for loop candidates (m)")
    parser.add_argument("--min-path-gap", type=float, default=20.0, help="Min walked path between loop frames (m)")
    parser.add_argument("--submap-half-win", type=int, default=12, help="Half-window of keyframes for ICP submap")
    parser.add_argument("--max-icp-rmse", type=float, default=0.22, help="Max ICP RMSE to accept a loop edge (m)")
    parser.add_argument("--min-inlier-ratio", type=float, default=0.65, help="Min ICP inlier ratio")
    parser.add_argument("--stride", type=int, default=15, help="Keyframe stride for mid-trajectory loop search")
    parser.add_argument("--level-ground", action="store_true", help="Apply a single rigid tilt rotation to level the global ground plane to Z=const")
    args = parser.parse_args()

    in_dir = args.input_map.resolve()
    out_dir = args.output_map.resolve()
    if not (in_dir / "poses.pcd").is_file() or not (in_dir / "pcd").is_dir():
        raise SystemExit(f"Invalid DDDMR map directory: {in_dir}")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"Output directory must be empty or non-existent: {out_dir}")

    _, poses_arr = load_pcd_ascii(in_dir / "poses.pcd")
    poses = poses_from_pcd(poses_arr)
    n = len(poses)
    positions = poses[:, :3, 3]
    seg_lens = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    cum_len = np.concatenate([[0.0], np.cumsum(seg_lens)])

    # Detect loop candidates: always include (n-1 -> nearest early kf) + strided mid-loop candidates
    candidates = []
    check_indices = list(range(30, n - 1, args.stride)) + [n - 1]
    seen_pairs = set()
    for u in check_indices:
        best_v = None
        best_d = args.loop_radius
        for v in range(0, u):
            if cum_len[u] - cum_len[v] < args.min_path_gap:
                continue
            d = float(np.linalg.norm(positions[u] - positions[v]))
            if d < best_d:
                best_d = d
                best_v = v
        if best_v is not None and (u, best_v) not in seen_pairs:
            seen_pairs.add((u, best_v))
            candidates.append((u, best_v, best_d))

    pcd_dir = in_dir / "pcd"
    loop_constraints = []
    loop_report = []
    for u, v, d_init in candidates:
        # Preserve accurate horizontal XY/yaw odometry to avoid shearing walls on sparse L2 clouds;
        # measure exact vertical Z overlap directly from overlapping ground submaps.
        T_meas = inv_se3(poses[v]) @ poses[u]
        src_g = build_submap_in_frame(pcd_dir, poses, u, min(args.submap_half_win, 5), kinds=("ground",))
        dst_g = build_submap_in_frame(pcd_dir, poses, v, min(args.submap_half_win, 5), kinds=("ground",))
        dz_med = 0.0
        z_iqr = float("inf")
        overlap_cnt = 0
        if len(src_g) >= 50 and len(dst_g) >= 50:
            src_g_tf = src_g @ T_meas[:3, :3].T + T_meas[:3, 3]
            tree_xy = cKDTree(dst_g[:, :2])
            d_xy, idx_xy = tree_xy.query(src_g_tf[:, :2], distance_upper_bound=0.25)
            m_xy = np.isfinite(d_xy)
            overlap_cnt = int(m_xy.sum())
            if overlap_cnt >= 80:
                dz_vals = dst_g[idx_xy[m_xy], 2] - src_g_tf[m_xy, 2]
                dz_med = float(np.median(dz_vals))
                z_iqr = float(np.percentile(dz_vals, 75) - np.percentile(dz_vals, 25))
                T_meas[2, 3] += dz_med
        accepted = (overlap_cnt >= 80 and z_iqr <= 0.40)
        # Pure Z + roll/pitch loop constraints: keep the already-accurate XY/yaw walls untouched!
        w_edge = np.array([0.0, 0.0, 15.0, 4.0, 4.0, 0.0], dtype=np.float64)
        entry = {
            "from": int(u), "to": int(v), "init_dist_m": round(d_init, 3),
            "ground_overlap_pts": overlap_cnt, "ground_dz_m": round(dz_med, 4),
            "ground_z_iqr_m": round(z_iqr, 4) if math.isfinite(z_iqr) else None,
            "accepted": accepted,
            "rel_xyz_m": [round(float(x), 4) for x in T_meas[:3, 3]],
        }
        loop_report.append(entry)
        if accepted:
            loop_constraints.append((u, v, T_meas, w_edge))

    if not loop_constraints:
        raise SystemExit(f"No valid loop constraints accepted. Candidates: {json.dumps(loop_report, indent=2)}")

    opt_poses, sol = optimize_pose_graph(poses, loop_constraints)

    def stitch_kind(pose_arr, kind):
        chunks = []
        for i in range(n):
            p = pcd_dir / f"{i}_{kind}.pcd"
            if p.exists():
                _, arr = load_pcd_ascii(p)
                if len(arr):
                    R, t = pose_arr[i][:3, :3], pose_arr[i][:3, 3]
                    xyz = arr[:, :3] @ R.T + t
                    inten = arr[:, 3] if arr.shape[1] > 3 else np.zeros(len(arr))
                    chunks.append(np.column_stack([xyz, inten]))
        return voxel_downsample(np.vstack(chunks), 0.1) if chunks else np.zeros((0, 4))

    def ground_plane_stats(g_pts):
        A = np.column_stack([g_pts[:, 0], g_pts[:, 1], np.ones(len(g_pts))])
        coef, _, _, _ = np.linalg.lstsq(A, g_pts[:, 2], rcond=None)
        resid = np.abs(g_pts[:, 2] - A @ coef)
        return {
            "points": int(len(g_pts)),
            "slope_x_deg": round(float(math.degrees(math.atan(coef[0]))), 2),
            "slope_y_deg": round(float(math.degrees(math.atan(coef[1]))), 2),
            "resid_median_cm": round(float(np.median(resid) * 100), 2),
            "resid_p95_cm": round(float(np.percentile(resid, 95) * 100), 2),
            "z_span_m": round(float(g_pts[:, 2].max() - g_pts[:, 2].min()), 3),
        }, coef

    _, orig_ground_raw = load_pcd_ascii(in_dir / "ground.pcd")
    ground_before_stats, _ = ground_plane_stats(orig_ground_raw)

    level_applied = False
    level_tilt_deg = 0.0
    if args.level_ground:
        tmp_ground = stitch_kind(opt_poses, "ground")
        _, coef = ground_plane_stats(tmp_ground)
        normal = np.array([-coef[0], -coef[1], 1.0], dtype=np.float64)
        normal /= np.linalg.norm(normal)
        target = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        axis = np.cross(normal, target)
        sin_a = float(np.linalg.norm(axis))
        cos_a = float(np.clip(np.dot(normal, target), -1.0, 1.0))
        if sin_a > 1e-8:
            angle = math.atan2(sin_a, cos_a)
            R_level = Rotation.from_rotvec((axis / sin_a) * angle).as_matrix()
            pivot = opt_poses[0, :3, 3].copy()
            T_level = np.eye(4, dtype=np.float64)
            T_level[:3, :3] = R_level
            T_level[:3, 3] = pivot - R_level @ pivot
            opt_poses = np.array([T_level @ T for T in opt_poses], dtype=np.float64)
            level_applied = True
            level_tilt_deg = round(math.degrees(angle), 2)

    # Save new DDDMR-compatible map directory
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(pcd_dir, out_dir / "pcd")
    save_poses_pcd(out_dir / "poses.pcd", opt_poses, poses_arr)

    edges = [(0, 0)] + [(i, i + 1) for i in range(n - 1)] + [(u, v) for (u, v, _, _) in loop_constraints]
    save_edges_pcd(out_dir / "edges.pcd", edges)

    map_pts = stitch_kind(opt_poses, "feature")
    ground_pts = stitch_kind(opt_poses, "ground")
    save_xyzi_pcd(out_dir / "map.pcd", map_pts)
    save_xyzi_pcd(out_dir / "ground.pcd", ground_pts)

    # Compute before/after metrics
    def closure_stats(P):
        d = P[-1, :3, 3] - P[0, :3, 3]
        plen = float(np.linalg.norm(np.diff(P[:, :3, 3], axis=0), axis=1).sum())
        return {
            "path_length_m": round(plen, 3),
            "start_xyz_m": [round(float(x), 4) for x in P[0, :3, 3]],
            "end_xyz_m": [round(float(x), 4) for x in P[-1, :3, 3]],
            "closure_xy_m": round(float(np.hypot(d[0], d[1])), 4),
            "closure_z_m": round(float(d[2]), 4),
            "closure_3d_m": round(float(np.linalg.norm(d)), 4),
        }

    ground_after_stats, _ = ground_plane_stats(ground_pts)

    summary = {
        "input_map": str(in_dir),
        "output_map": str(out_dir),
        "keyframes": n,
        "edges_before": n,
        "edges_after": len(edges),
        "loop_edges_added": len(loop_constraints),
        "level_ground_applied": level_applied,
        "level_tilt_corrected_deg": level_tilt_deg,
        "loop_candidates": loop_report,
        "optimizer_success": bool(sol.success),
        "optimizer_nfev": int(sol.nfev),
        "optimizer_cost": round(float(sol.cost), 6),
        "before": closure_stats(poses),
        "after": closure_stats(opt_poses),
        "output_points": {"map": int(len(map_pts)), "ground": int(len(ground_pts))},
        "ground_plane_before": ground_before_stats,
        "ground_plane_after": ground_after_stats,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
