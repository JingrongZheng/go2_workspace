#!/usr/bin/env python3
"""Read-only /cmd_vel auditor for R4 dry-run; logs velocities and never controls the robot."""
import argparse
import json
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node


class CmdVelAudit(Node):
    def __init__(self, log_path: Path):
        super().__init__("go2_cmd_vel_audit")
        self.log_file = open(log_path, "a", buffering=1)
        self.count = 0
        self.nonzero = 0
        self.last_print = 0.0
        self.max_vx = 0.0
        self.max_wz = 0.0
        self.sub = self.create_subscription(Twist, "/cmd_vel", self.cb, 20)

    def cb(self, msg: Twist):
        self.count += 1
        vx, vy, wz = msg.linear.x, msg.linear.y, msg.angular.z
        if abs(vx) > 1e-4 or abs(vy) > 1e-4 or abs(wz) > 1e-4:
            self.nonzero += 1
        self.max_vx = max(self.max_vx, abs(vx))
        self.max_wz = max(self.max_wz, abs(wz))
        now = time.time()
        self.log_file.write(json.dumps({
            "t": round(now, 3), "vx": round(vx, 4), "vy": round(vy, 4), "wz": round(wz, 4)
        }) + "\n")
        if now - self.last_print >= 1.0:
            self.last_print = now
            self.get_logger().info(
                f"[R4 DRY-RUN /cmd_vel] vx={vx:+.3f} m/s, vy={vy:+.3f}, wz={wz:+.3f} rad/s "
                f"(msgs={self.count}, nonzero={self.nonzero}, max_vx={self.max_vx:.3f}, max_wz={self.max_wz:.3f})"
            )

    def close(self):
        self.log_file.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log", type=Path, required=True)
    args = p.parse_args()
    rclpy.init(args=[])
    node = CmdVelAudit(args.log)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.close()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
