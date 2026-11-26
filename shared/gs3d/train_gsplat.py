#!/usr/bin/env python3
"""6 GB VRAM-friendly 3D Gaussian Splatting trainer using gsplat with optional D435i depth supervision."""
import argparse
import json
import math
from pathlib import Path
import time

import numpy as np
from PIL import Image
from plyfile import PlyData, PlyElement
import torch
import torch.nn.functional as F
from gsplat.rendering import rasterization
from gsplat.strategy import DefaultStrategy


def qvec2rotmat(qvec):
    w, x, y, z = qvec
    return np.array([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * z * w, 2 * x * z + 2 * y * w],
        [2 * x * y + 2 * z * w, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * x * w],
        [2 * x * z - 2 * y * w, 2 * y * z + 2 * x * w, 1 - 2 * x * x - 2 * y * y],
    ], dtype=np.float32)


def rgb_to_sh(rgb: torch.Tensor) -> torch.Tensor:
    return (rgb - 0.5) / 0.28209479177387814


def ssim_loss(img1: torch.Tensor, img2: torch.Tensor, window_size: int = 11) -> torch.Tensor:
    # img1, img2: [1, C, H, W]
    c = img1.shape[1]
    coords = torch.arange(window_size, dtype=img1.dtype, device=img1.device) - window_size // 2
    g = torch.exp(-(coords ** 2) / (2 * 1.5 ** 2))
    g = g / g.sum()
    window = (g[:, None] @ g[None, :]).expand(c, 1, window_size, window_size).contiguous()
    pad = window_size // 2
    mu1 = F.conv2d(img1, window, padding=pad, groups=c)
    mu2 = F.conv2d(img2, window, padding=pad, groups=c)
    mu1_sq, mu2_sq, mu1_mu2 = mu1 * mu1, mu2 * mu2, mu1 * mu2
    sigma1_sq = F.conv2d(img1 * img1, window, padding=pad, groups=c) - mu1_sq
    sigma2_sq = F.conv2d(img2 * img2, window, padding=pad, groups=c) - mu2_sq
    sigma12 = F.conv2d(img1 * img2, window, padding=pad, groups=c) - mu1_mu2
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / ((mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2))
    return 1.0 - ssim_map.mean()


def load_scene(dataset_dir: Path, sparse_txt: Path, device: torch.device):
    intr = json.loads((dataset_dir / "intrinsics.json").read_text())
    depth_scale = float(intr.get("depth_scale", 0.001))

    cameras = {}
    for line in (sparse_txt / "cameras.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split()
        cid = int(p[0])
        cameras[cid] = (int(p[2]), int(p[3]), [float(v) for v in p[4:]])

    views = []
    img_lines = [l for l in (sparse_txt / "images.txt").read_text().splitlines() if l and not l.startswith("#")]
    for i in range(0, len(img_lines), 2):
        p = img_lines[i].split()
        qvec = [float(v) for v in p[1:5]]
        tvec = np.array([float(v) for v in p[5:8]], dtype=np.float32)
        cid = int(p[8])
        name = Path(p[9]).name
        w, h, cp = cameras[cid]
        fx, fy, cx, cy = cp[0], cp[1], cp[2], cp[3]
        K = torch.tensor([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=torch.float32)
        viewmat = np.eye(4, dtype=np.float32)
        viewmat[:3, :3] = qvec2rotmat(qvec)
        viewmat[:3, 3] = tvec
        rgb_np = np.asarray(Image.open(dataset_dir / "images" / name).convert("RGB"), dtype=np.float32) / 255.0
        dep_path = dataset_dir / "depth" / f"{Path(name).stem}.png"
        dep_np = None
        if dep_path.exists():
            dep_np = np.asarray(Image.open(dep_path), dtype=np.float32) * depth_scale
        views.append({
            "name": name,
            "width": w,
            "height": h,
            "K": K,
            "viewmat": torch.from_numpy(viewmat),
            "rgb": torch.from_numpy(rgb_np),  # Keep on CPU; move per-step to save 6 GB VRAM!
            "depth": torch.from_numpy(dep_np) if dep_np is not None else None,
        })

    xyz_list, rgb_list = [], []
    for line in (sparse_txt / "points3D.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split()
        xyz_list.append([float(p[1]), float(p[2]), float(p[3])])
        rgb_list.append([float(p[4]) / 255.0, float(p[5]) / 255.0, float(p[6]) / 255.0])
    xyz = np.asarray(xyz_list, dtype=np.float32)
    rgb = np.asarray(rgb_list, dtype=np.float32)
    if len(xyz) > 120000:
        idx = np.random.default_rng(0).choice(len(xyz), size=120000, replace=False)
        xyz, rgb = xyz[idx], rgb[idx]

    # Estimate initial Gaussian scales from 3-NN distances (batched on CPU via scipy)
    from scipy.spatial import cKDTree
    dists, _ = cKDTree(xyz).query(xyz, k=4)
    avg_dist = np.clip(np.mean(dists[:, 1:], axis=1), 0.005, 0.25).astype(np.float32)

    cam_centers = np.stack([-(v["viewmat"][:3, :3].numpy().T @ v["viewmat"][:3, 3].numpy()) for v in views])
    scene_scale = float(np.max(np.linalg.norm(cam_centers - cam_centers.mean(axis=0), axis=1)) * 1.1)
    scene_scale = max(scene_scale, 1.0)
    return views, torch.from_numpy(xyz).to(device), torch.from_numpy(rgb).to(device), torch.from_numpy(avg_dist).to(device), scene_scale


def export_ply(path: Path, params: dict):
    means = params["means"].detach().cpu().numpy()
    sh0 = params["sh0"].detach().cpu().numpy()[:, 0, :]  # [N, 3]
    shN = params["shN"].detach().cpu().numpy().transpose(0, 2, 1).reshape(len(means), -1)  # [N, 3*(K-1)]
    opacities = params["opacities"].detach().cpu().numpy()[:, None]
    scales = params["scales"].detach().cpu().numpy()
    quats = F.normalize(params["quats"].detach(), dim=-1).cpu().numpy()
    normals = np.zeros_like(means)

    attrs = (
        ["x", "y", "z", "nx", "ny", "nz"]
        + [f"f_dc_{i}" for i in range(3)]
        + [f"f_rest_{i}" for i in range(shN.shape[1])]
        + ["opacity"]
        + [f"scale_{i}" for i in range(3)]
        + [f"rot_{i}" for i in range(4)]
    )
    dtype = [(a, "f4") for a in attrs]
    data = np.concatenate([means, normals, sh0, shN, opacities, scales, quats], axis=1)
    elements = np.empty(len(means), dtype=dtype)
    elements[:] = list(map(tuple, data))
    PlyData([PlyElement.describe(elements, "vertex")]).write(str(path))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--sparse-txt", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--steps", type=int, default=15000)
    p.add_argument("--sh-degree", type=int, default=2, help="SH degree (2 saves VRAM on 6GB GPU)")
    p.add_argument("--depth-weight", type=float, default=0.1, help="D435i metric depth L1 weight")
    p.add_argument("--max-gaussians", type=int, default=350000, help="VRAM safety cap for RTX 3060 6GB")
    args = p.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[3DGS] Device: {device} ({torch.cuda.get_device_name(0) if device.type == 'cuda' else 'CPU'})", flush=True)

    views, xyz, rgb, avg_dist, scene_scale = load_scene(args.dataset, args.sparse_txt, device)
    n_pts = len(xyz)
    n_sh = (args.sh_degree + 1) ** 2
    print(f"[3DGS] Loaded {len(views)} views, {n_pts} init points, scene_scale={scene_scale:.2f} m", flush=True)

    params = torch.nn.ParameterDict({
        "means": torch.nn.Parameter(xyz),
        "scales": torch.nn.Parameter(torch.log(avg_dist[:, None].repeat(1, 3))),
        "quats": torch.nn.Parameter(torch.tensor([[1.0, 0.0, 0.0, 0.0]], device=device).repeat(n_pts, 1)),
        "opacities": torch.nn.Parameter(torch.logit(torch.full((n_pts,), 0.1, device=device))),
        "sh0": torch.nn.Parameter(rgb_to_sh(rgb)[:, None, :]),
        "shN": torch.nn.Parameter(torch.zeros((n_pts, n_sh - 1, 3), device=device)),
    })

    lrs = {
        "means": 1.6e-4 * scene_scale,
        "scales": 5e-3,
        "quats": 1e-3,
        "opacities": 5e-2,
        "sh0": 2.5e-3,
        "shN": 2.5e-3 / 20.0,
    }
    optimizers = {
        k: torch.optim.Adam([{"params": params[k], "lr": lr, "name": k}], eps=1e-15)
        for k, lr in lrs.items()
    }
    means_sched = torch.optim.lr_scheduler.ExponentialLR(
        optimizers["means"], gamma=0.01 ** (1.0 / max(1, args.steps))
    )

    strategy = DefaultStrategy(
        prune_opa=0.005,
        grow_grad2d=0.00025,
        grow_scale3d=0.01,
        prune_scale3d=0.1,
        refine_start_iter=500,
        refine_stop_iter=min(10000, int(args.steps * 0.7)),
        reset_every=3000,
        refine_every=150,
        absgrad=False,
    )
    strategy.check_sanity(params, optimizers)
    strategy_state = strategy.initialize_state(scene_scale=scene_scale)

    t0 = time.monotonic()
    rng = np.random.default_rng(42)
    last_psnr = 0.0

    for step in range(1, args.steps + 1):
        view = views[int(rng.integers(0, len(views)))]
        gt_rgb = view["rgb"].to(device, non_blocking=True)
        K = view["K"].to(device, non_blocking=True)[None]
        viewmat = view["viewmat"].to(device, non_blocking=True)[None]
        sh_deg = min(step // 1000, args.sh_degree)

        colors = torch.cat([params["sh0"], params["shN"]], dim=1)
        render_mode = "RGB+ED" if (args.depth_weight > 0 and view["depth"] is not None) else "RGB"
        renders, alphas, info = rasterization(
            means=params["means"],
            quats=F.normalize(params["quats"], dim=-1),
            scales=torch.exp(params["scales"]),
            opacities=torch.sigmoid(params["opacities"]),
            colors=colors,
            viewmats=viewmat,
            Ks=K,
            width=view["width"],
            height=view["height"],
            sh_degree=sh_deg,
            packed=True,
            render_mode=render_mode,
        )

        pred_rgb = renders[0, ..., :3].clamp(0.0, 1.0)
        l1 = F.l1_loss(pred_rgb, gt_rgb)
        ssim = ssim_loss(pred_rgb.permute(2, 0, 1)[None], gt_rgb.permute(2, 0, 1)[None])
        loss = 0.8 * l1 + 0.2 * ssim

        if render_mode == "RGB+ED":
            gt_dep = view["depth"].to(device, non_blocking=True)
            valid = (gt_dep >= 0.35) & (gt_dep <= 4.5)
            if valid.any():
                pred_dep = renders[0, ..., 3]
                loss = loss + args.depth_weight * F.l1_loss(pred_dep[valid], gt_dep[valid])

        strategy.step_pre_backward(params=params, optimizers=optimizers, state=strategy_state, step=step, info=info)
        loss.backward()
        for opt in optimizers.values():
            opt.step()
            opt.zero_grad(set_to_none=True)
        means_sched.step()

        # Enforce 6 GB VRAM Gaussian count cap
        if len(params["means"]) < args.max_gaussians:
            strategy.step_post_backward(
                params=params, optimizers=optimizers, state=strategy_state, step=step, info=info, packed=True
            )

        if step % 1000 == 0 or step == args.steps:
            with torch.no_grad():
                mse = F.mse_loss(pred_rgb, gt_rgb).item()
                last_psnr = -10.0 * math.log10(max(mse, 1e-10))
                vram_mb = torch.cuda.max_memory_allocated() / 1e6 if device.type == "cuda" else 0.0
                print(
                    f"[3DGS] step {step:5d}/{args.steps} | loss={loss.item():.4f} | "
                    f"psnr={last_psnr:.2f} dB | splats={len(params['means']):,} | "
                    f"peak_vram={vram_mb:.0f} MB | elapsed={time.monotonic()-t0:.1f}s",
                    flush=True,
                )

    ply_path = args.output / "point_cloud.ply"
    export_ply(ply_path, params)
    elapsed = time.monotonic() - t0
    metrics = {
        "steps": args.steps,
        "views": len(views),
        "num_gaussians": int(len(params["means"])),
        "final_psnr_db": round(last_psnr, 2),
        "elapsed_s": round(elapsed, 1),
        "ply": str(ply_path),
    }
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(f"[3DGS] Saved {ply_path} ({metrics['num_gaussians']:,} splats, {elapsed:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
