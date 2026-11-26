#!/usr/bin/env python3
"""Translate PC ROS 2 /cmd_vel (domain 84) into bounded Go2 Sport requests over SSH.

Reuses the already-deployed onboard go2_wifi_control_source.py receiver (which enforces
|vx|<=0.35 m/s, vy=0, |wz|<=1.0 rad/s, 0.4s freshness, 0.8s watchdog, and disconnect StopMove).
Default mode (without --robot) is dry-run preview with no onboard DDS publisher.
"""
import argparse
import ipaddress
import json
import math
import os
import select
import shlex
import struct
import subprocess
import sys
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

ROOT = Path(__file__).resolve().parent.parent
ESTOP_LOCK = ROOT / ".work/estop.lock"
sys.path.insert(0, str(ROOT / "shared"))
from go2_estop import measure_pc_minus_dock, remote_command

MOVE = 1008
STOP_MOVE = 1003
PUBLISH_PERIOD_S = 0.1  # 10 Hz
CMD_TIMEOUT_S = 0.5     # Send StopMove if /cmd_vel goes silent for > 0.5 s
VX_DEADBAND = 0.02
WZ_DEADBAND = 0.05


def clamp_velocity(vx: float, wz: float, max_vx: float, max_wz: float):
    if not (math.isfinite(vx) and math.isfinite(wz)):
        return 0.0, 0.0
    vx = max(-max_vx, min(max_vx, vx))
    wz = max(-max_wz, min(max_wz, wz))
    if abs(vx) < VX_DEADBAND:
        vx = 0.0
    if abs(wz) < WZ_DEADBAND:
        wz = 0.0
    return vx, wz


class CmdVelBridgeNode(Node):
    def __init__(self, args, proc):
        super().__init__("go2_cmd_vel_bridge")
        self.args = args
        self.proc = proc
        self.latest = None  # (mono_t, vx, wz)
        self.moving = False
        self.sent_moves = 0
        self.sent_stops = 0
        self.last_status = 0.0
        self.sub = self.create_subscription(Twist, args.topic, self.on_twist, 10)
        self.timer = self.create_timer(PUBLISH_PERIOD_S, self.tick)

    def on_twist(self, msg: Twist):
        vx, wz = clamp_velocity(msg.linear.x, msg.angular.z, self.args.max_vx, self.args.max_wz)
        self.latest = (time.monotonic(), vx, wz)

    def send_packet(self, api_id: int, parameter: str = ""):
        if self.proc.poll() is not None:
            raise ConnectionError(f"Onboard control SSH exited with code {self.proc.returncode}")
        payload = (json.dumps({
            "api_id": api_id,
            "parameter": parameter,
            "sent_pc_ns": time.time_ns(),
        }) + "\n").encode()
        if os.write(self.proc.stdin.fileno(), payload) != len(payload):
            raise ConnectionError("Partial write to onboard control SSH pipe")

    def send_stop(self, reason: str):
        if not self.moving:
            return
        self.send_packet(STOP_MOVE)
        self.moving = False
        self.sent_stops += 1
        self.get_logger().info(f"[BRIDGE] StopMove ({reason}; moves={self.sent_moves}, stops={self.sent_stops})")

    def tick(self):
        now = time.monotonic()
        if ESTOP_LOCK.exists():
            self.send_stop("estop_lock")
            if now - self.last_status >= 2.0:
                self.last_status = now
                self.get_logger().warn("[BRIDGE] BLOCKED by .work/estop.lock (press R in estop terminal to release)")
            return
        if self.latest is None or (now - self.latest[0]) > CMD_TIMEOUT_S:
            self.send_stop("cmd_vel_timeout")
            return
        _, vx, wz = self.latest
        if vx == 0.0 and wz == 0.0:
            self.send_stop("zero_cmd")
            return
        param = json.dumps({"x": round(vx, 4), "y": 0.0, "z": round(wz, 4)})
        self.send_packet(MOVE, param)
        self.moving = True
        self.sent_moves += 1
        if now - self.last_status >= 1.0:
            self.last_status = now
            tag = "LIVE" if self.args.robot else "PREVIEW"
            self.get_logger().info(f"[BRIDGE {tag}] Move vx={vx:+.3f} m/s, wz={wz:+.3f} rad/s (moves={self.sent_moves})")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", type=ipaddress.IPv4Address, default="192.168.123.18")
    p.add_argument("--socket", type=Path, default=ROOT / ".work/ssh-control/go2.sock")
    p.add_argument("--topic", default="/cmd_vel")
    p.add_argument("--max-vx", type=float, default=0.35, help="Max linear speed m/s (<= 0.35)")
    p.add_argument("--max-wz", type=float, default=0.80, help="Max angular speed rad/s (<= 1.0)")
    p.add_argument("--check", action="store_true", help="Read-only check of onboard sport subscriber")
    p.add_argument("--robot", action="store_true", help="Enable live publishing to /api/sport/request")
    args = p.parse_args()

    if not (0.0 < args.max_vx <= 0.35):
        p.error("--max-vx must be in (0, 0.35] m/s")
    if not (0.0 < args.max_wz <= 1.0):
        p.error("--max-wz must be in (0, 1.0] rad/s")

    cmd = [
        "ssh", "-T", "-S", str(args.socket),
        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=1", "-o", "ServerAliveCountMax=2",
        f"unitree@{args.host}",
        "bash -c " + shlex.quote(remote_command(args.check, not args.robot and not args.check)),
    ]
    if args.check:
        return subprocess.call(cmd)

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
    node = None
    try:
        offset = measure_pc_minus_dock(proc)
        proc.stdin.write(b"S" + struct.pack("!q", offset))
        proc.stdin.flush()
        if not select.select([proc.stdout], [], [], 8.0)[0]:
            raise TimeoutError("Onboard control receiver did not become ready")
        status = json.loads(proc.stdout.readline())
        if not status.get("ready"):
            raise RuntimeError(status.get("error", "Onboard receiver failed"))

        banner = (
            f"=== LIVE /cmd_vel -> Go2 SPORT BRIDGE ARMED (max_vx={args.max_vx:.2f} m/s, max_wz={args.max_wz:.2f} rad/s) ==="
            if args.robot else
            f"=== PREVIEW /cmd_vel BRIDGE (dry-run; no real robot requests published) ==="
        )
        print(banner, flush=True)
        print("Press Ctrl+C to immediately send StopMove and disconnect. Keep './go2 estop --robot' ready.", flush=True)

        os.set_blocking(proc.stdin.fileno(), False)
        rclpy.init(args=[])
        node = CmdVelBridgeNode(args, proc)
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        if node is not None:
            try:
                node.send_stop("shutdown")
            except Exception:
                pass
            node.destroy_node()
            rclpy.try_shutdown()
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
