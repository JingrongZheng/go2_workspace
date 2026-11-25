#!/usr/bin/env python3
"""Display the latest ROS 2 Go2 camera image in a separate GUI process."""

import cv2
import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import Image

WINDOW = "Go2 front camera"


def main():
    rclpy.init()
    node = rclpy.create_node("go2_camera_viewer")
    latest = None
    opened = False

    def receive(message):
        nonlocal latest
        latest = message

    node.create_subscription(Image, "/go2/webrtc/image", receive, 1)
    cv2.setNumThreads(1)
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.01)
            if latest is not None:
                message, latest = latest, None
                pixels = np.frombuffer(message.data, dtype=np.uint8)
                rows = pixels.reshape(message.height, message.step)
                rgb = rows[:, :message.width * 3].reshape(message.height, message.width, 3)
                if not opened:
                    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
                    cv2.resizeWindow(WINDOW, 640, 360)
                    opened = True
                cv2.imshow(WINDOW, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            if opened:
                if cv2.waitKey(1) & 0xFF == 27:
                    break
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_AUTOSIZE) < 0:
                    break
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
