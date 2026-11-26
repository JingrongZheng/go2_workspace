#!/usr/bin/env python3
"""Record color-aligned D435i RGB-D keyframes, factory intrinsics, and optional DDDMR poses over SSH."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import queue
import shlex
import struct
import subprocess
import sys
import threading
import time
import zlib

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FRAME_HDR = struct.Struct("<4sIqdII")


class StreamEnded(RuntimeError):
    pass


def read_exact(stream, size: int) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        chunk = stream.read(size - len(buf))
        if not chunk:
            raise StreamEnded("Camera stream ended.")
        buf.extend(chunk)
    return bytes(buf)


class RosPoseTracker:
    """Optional background subscriber to DDDMR /mcl_pose (PoseWithCovarianceStamped) on ROS domain 84."""

    def __init__(self, topic: str = "/mcl_pose"):
        self.topic = topic
        self.available = False
        self._lock = threading.Lock()
        self._samples = []  # list of (pc_wall_ns, [x, y, z, qx, qy, qz, qw])
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        try:
            import rclpy
            from geometry_msgs.msg import PoseWithCovarianceStamped
        except Exception:
            return False

        def worker():
            try:
                rclpy.init(args=[])
                node = rclpy.create_node("go2_rgbd_pose_sync")

                def on_pose(msg):
                    p = msg.pose.pose.position
                    q = msg.pose.pose.orientation
                    ts = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
                    if ts == 0:
                        ts = time.time_ns()
                    with self._lock:
                        self._samples.append((ts, [p.x, p.y, p.z, q.x, q.y, q.z, q.w]))
                        if len(self._samples) > 4000:
                            self._samples = self._samples[-2000:]

                node.create_subscription(PoseWithCovarianceStamped, self.topic, on_pose, 10)
                while not self._stop.is_set() and rclpy.ok():
                    rclpy.spin_once(node, timeout_sec=0.05)
                node.destroy_node()
                rclpy.try_shutdown()
            except Exception:
                pass

        self.available = True
        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
        return True

    def lookup(self, target_ns: int, max_dt_ns: int = 500_000_000):
        with self._lock:
            if not self._samples:
                return None, None
            best = min(self._samples, key=lambda item: abs(item[0] - target_ns))
        dt_ns = abs(best[0] - target_ns)
        if dt_ns > max_dt_ns:
            return None, None
        return best[1], round(dt_ns / 1e6, 2)

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)


def start_sender(host: str, control: Path | None, width: int, height: int, fps: int, target_hz: float):
    remote = f"""set -e
umask 077
mkdir -p "$HOME/.local/share/go2-rgbd-gs"
cd "$HOME/.local/share/go2-rgbd-gs"
cat > sender.cpp
if ! command -v g++ >/dev/null; then
  echo 'g++ is missing on the onboard computer.' >&2
  exit 1
fi
if command -v pkg-config >/dev/null && pkg-config --exists realsense2; then
  g++ -O2 -std=c++17 sender.cpp -o sender $(pkg-config --cflags --libs realsense2) -ljpeg -lz
else
  g++ -O2 -std=c++17 sender.cpp -o sender -I/usr/local/include -L/usr/local/lib -Wl,-rpath,/usr/local/lib -lrealsense2 -ljpeg -lz
fi
echo "SSH transport: $SSH_CONNECTION" >&2
exec ./sender --width {width} --height {height} --fps {fps} --target-hz {target_hz}
"""
    opts = ["-S", str(control), "-o", "BatchMode=yes"] if control else []
    src = Path(__file__).with_name("rgbd_keyframe_sender.cpp")
    with src.open("rb") as fh:
        return subprocess.Popen(
            [
                "ssh", *opts, "-T",
                "-o", "ConnectTimeout=8",
                "-o", "ServerAliveInterval=3",
                "-o", "ServerAliveCountMax=2",
                "--", host, "bash -c " + shlex.quote(remote),
            ],
            stdin=fh, stdout=subprocess.PIPE,
        )


def compute_sharpness(bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="unitree@192.168.123.18")
    p.add_argument("--ssh-control", type=Path, help="Existing SSH control socket")
    p.add_argument("--output", type=Path, help="New output dataset directory")
    p.add_argument("--width", type=int, default=848)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=15)
    p.add_argument("--hz", type=float, default=2.5, help="Keyframe capture rate (default 2.5 Hz)")
    p.add_argument("--min-sharpness", type=float, default=0.0,
                   help="Optional Laplacian variance threshold to skip blurry frames (0 = keep all)")
    p.add_argument("--duration", type=float, default=0.0, help="Seconds to record (0 = until Q/Esc/Ctrl+C)")
    p.add_argument("--pose-topic", default="/mcl_pose", help="Optional ROS 2 PoseWithCovarianceStamped topic")
    p.add_argument("--no-ros-pose", action="store_true", help="Disable optional ROS 2 /mcl_pose sync")
    p.add_argument("--no-display", action="store_true", help="Disable live OpenCV preview window")
    args = p.parse_args()

    out = (args.output or (ROOT / ".work/sessions" / datetime.now().strftime("rgbd-%Y%m%d-%H%M%S"))).resolve()
    images_dir = out / "images"
    depth_dir = out / "depth"
    images_dir.mkdir(parents=True, exist_ok=False)
    depth_dir.mkdir(parents=True, exist_ok=True)
    frames_log = (out / "frames.jsonl").open("w", encoding="utf-8")

    pose_tracker = None
    if not args.no_ros_pose:
        pose_tracker = RosPoseTracker(args.pose_topic)
        if pose_tracker.start():
            print(f"[RGBD] Optional ROS 2 pose sync enabled on {args.pose_topic}", flush=True)
        else:
            pose_tracker = None

    print(f"[RGBD] Output dataset: {out}", flush=True)
    print(f"[RGBD] Capturing {args.width}x{args.height} aligned RGB-D keyframes @ {args.hz:.1f} Hz ...", flush=True)
    print("[RGBD] Walk slowly in a loop around the lab with rich texture. Press Q / Esc / Ctrl+C to stop.", flush=True)

    cv2.setNumThreads(1)
    proc = start_sender(args.host, args.ssh_control, args.width, args.height, args.fps, args.hz)
    stop = threading.Event()
    latest = queue.Queue(maxsize=1)
    finished = threading.Event()
    stats = {"saved": 0, "skipped_blur": 0, "with_pose": 0, "bytes": 0, "last_frame": None}
    errors = []

    def receive():
        try:
            magic = read_exact(proc.stdout, 8)
            if magic != b"GO2GS001":
                raise ValueError(f"Unexpected stream magic: {magic!r}")
            hdr_len, = struct.unpack("<I", read_exact(proc.stdout, 4))
            meta = json.loads(read_exact(proc.stdout, hdr_len).decode("utf-8"))
            meta["captured_at"] = datetime.now().isoformat()
            meta["host"] = args.host
            (out / "intrinsics.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            w, h = int(meta["width"]), int(meta["height"])
            print(
                f"[RGBD] Intrinsics saved: {w}x{h}, fx={meta['fx']:.2f}, fy={meta['fy']:.2f}, "
                f"cx={meta['cx']:.2f}, cy={meta['cy']:.2f}, depth_scale={meta['depth_scale']}",
                flush=True,
            )

            started = None
            while not stop.is_set():
                fmagic, seq, dock_ns, sensor_ms, rgb_sz, depth_sz = FRAME_HDR.unpack(
                    read_exact(proc.stdout, FRAME_HDR.size)
                )
                if fmagic != b"KF01":
                    raise ValueError(f"Unexpected frame magic: {fmagic!r}")
                rgb_bytes = read_exact(proc.stdout, rgb_sz)
                depth_zbytes = read_exact(proc.stdout, depth_sz)
                pc_ns = time.time_ns()

                bgr = cv2.imdecode(np.frombuffer(rgb_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                if bgr is None or bgr.shape[:2] != (h, w):
                    raise ValueError("Corrupt RGB JPEG frame")
                depth_raw = zlib.decompress(depth_zbytes)
                depth_u16 = np.frombuffer(depth_raw, dtype=np.uint16).reshape((h, w))

                sharpness = compute_sharpness(bgr)
                now = time.monotonic()
                if started is None:
                    started = now
                stats["last_frame"] = now
                stats["bytes"] += FRAME_HDR.size + rgb_sz + depth_sz

                if args.min_sharpness > 0.0 and sharpness < args.min_sharpness:
                    stats["skipped_blur"] += 1
                else:
                    idx = stats["saved"]
                    img_rel = f"images/frame_{idx:05d}.jpg"
                    dep_rel = f"depth/frame_{idx:05d}.png"
                    (out / img_rel).write_bytes(rgb_bytes)
                    cv2.imwrite(str(out / dep_rel), depth_u16)

                    mcl_pose, pose_dt_ms = (None, None)
                    if pose_tracker is not None:
                        mcl_pose, pose_dt_ms = pose_tracker.lookup(pc_ns)
                        if mcl_pose is not None:
                            stats["with_pose"] += 1

                    record = {
                        "idx": idx,
                        "seq": seq,
                        "image": img_rel,
                        "depth": dep_rel,
                        "dock_wall_ns": dock_ns,
                        "pc_wall_ns": pc_ns,
                        "sensor_ts_ms": sensor_ms,
                        "sharpness": round(sharpness, 2),
                        "mcl_pose_map": mcl_pose,
                        "mcl_pose_dt_ms": pose_dt_ms,
                    }
                    frames_log.write(json.dumps(record) + "\n")
                    frames_log.flush()
                    stats["saved"] += 1

                try:
                    latest.get_nowait()
                except queue.Empty:
                    pass
                latest.put_nowait((bgr, depth_u16, sharpness))

                if args.duration > 0 and (now - started) >= args.duration:
                    break
        except Exception as err:
            if not stop.is_set():
                errors.append(err)
        finally:
            finished.set()

    worker = threading.Thread(target=receive, daemon=True)
    worker.start()

    try:
        next_report = time.monotonic() + 5.0
        while not finished.is_set():
            now = time.monotonic()
            if stats["last_frame"] is not None and (now - stats["last_frame"]) > 10.0:
                raise TimeoutError("No D435i frames received for 10 seconds.")
            if now >= next_report:
                next_report = now + 5.0
                mb = stats["bytes"] / 1e6
                print(
                    f"[RGBD] saved={stats['saved']} (with_pose={stats['with_pose']}, "
                    f"blur_skip={stats['skipped_blur']}), received={mb:.1f} MB",
                    flush=True,
                )
            if not args.no_display:
                try:
                    bgr, depth_u16, sharpness = latest.get(timeout=0.05)
                    depth_vis = cv2.applyColorMap(
                        cv2.convertScaleAbs(depth_u16, alpha=255.0 / 5000.0), cv2.COLORMAP_TURBO
                    )
                    panel = np.hstack([
                        cv2.resize(bgr, (640, 360)),
                        cv2.resize(depth_vis, (640, 360)),
                    ])
                    cv2.putText(
                        panel,
                        f"Saved: {stats['saved']} | Pose: {stats['with_pose']} | Sharp: {sharpness:.0f} | Q=stop",
                        (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
                    )
                    cv2.imshow("Go2 D435i 3DGS Capture (RGB | Aligned Depth)", panel)
                except queue.Empty:
                    pass
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    stop.set()
                    break
            else:
                time.sleep(0.05)
    except KeyboardInterrupt:
        stop.set()
    finally:
        stop.set()
        if pose_tracker is not None:
            pose_tracker.stop()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        worker.join(timeout=2.0)
        frames_log.close()
        if not args.no_display:
            cv2.destroyAllWindows()

    print(
        f"[RGBD] Finished: saved={stats['saved']} keyframes, with_pose={stats['with_pose']}, "
        f"dataset={out}",
        flush=True,
    )
    if errors:
        print(f"[RGBD] Error: {errors[0]}", file=sys.stderr)
        return 1
    return 0 if stats["saved"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
