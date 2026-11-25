#!/usr/bin/env python3
"""Send Go2 Sport requests from a Linux PC terminal."""

import argparse
import json
import os
import select
import sys
import termios
import time
import tty

import rclpy
from rclpy.signals import SignalHandlerOptions
from unitree_api.msg import Request

DEFAULT_LINEAR_SPEED = 0.35
TURN_SPEED = 1.0
MOVE = 1008
STOP_MOVE = 1003
REQUEST_TOPIC = "/api/sport/request"
COMMAND_TIMEOUT = 0.4
FIRST_REPEAT_TIMEOUT = 0.65
PUBLISH_INTERVAL = 0.1

POSTURE_COMMANDS = {
    "1": 1004,  # StandUp
    "2": 1002,  # BalanceStand
    "3": 1005,  # StandDown
    "4": 1001,  # Damp
}

VELOCITIES = {
    "w": (1.0, 0.0, 0.0),
    "s": (-1.0, 0.0, 0.0),
    "a": (0.0, 0.0, TURN_SPEED),
    "d": (0.0, 0.0, -TURN_SPEED),
}


def sport_request(api_id, velocity=None):
    request = Request()
    request.header.identity.api_id = api_id
    if velocity is not None:
        x, y, z = velocity
        request.parameter = json.dumps({"x": x, "y": y, "z": z})
    return request


def drive(send, input_fd, linear_speed):
    velocity = None
    deadline = 0.0
    next_publish = 0.0

    try:
        while True:
            ready, _, _ = select.select([input_fd], [], [], PUBLISH_INTERVAL)
            now = time.monotonic()
            if ready:
                key = os.read(input_fd, 1).decode("ascii", errors="ignore").lower()
                if key in ("q", ""):
                    return
                if key == " ":
                    send(sport_request(STOP_MOVE))
                    velocity = None
                elif key in POSTURE_COMMANDS:
                    if velocity is not None:
                        send(sport_request(STOP_MOVE))
                        velocity = None
                    send(sport_request(POSTURE_COMMANDS[key]))
                elif key in VELOCITIES:
                    x, y, z = VELOCITIES[key]
                    target = (x * linear_speed, y, z)
                    if velocity != target:
                        next_publish = now
                        # The first OS key repeat arrives later than subsequent repeats.
                        deadline = now + FIRST_REPEAT_TIMEOUT
                    else:
                        deadline = now + COMMAND_TIMEOUT
                    velocity = target

            if velocity is None:
                continue
            if now >= deadline:
                send(sport_request(STOP_MOVE))
                velocity = None
            elif now >= next_publish:
                send(sport_request(MOVE, velocity))
                next_publish = now + PUBLISH_INTERVAL
    finally:
        if velocity is not None:
            send(sport_request(STOP_MOVE))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot", action="store_true", help="Publish live DDS requests.")
    parser.add_argument(
        "--linear-speed", type=float, default=DEFAULT_LINEAR_SPEED,
        help="Forward/back speed in m/s (default: %(default)s)."
    )
    parser.add_argument("--request-topic", default=REQUEST_TOPIC, help="ROS 2 request destination.")
    args = parser.parse_args()
    if not 0 < args.linear_speed <= DEFAULT_LINEAR_SPEED:
        parser.error(f"--linear-speed must be greater than 0 and at most {DEFAULT_LINEAR_SPEED} m/s.")
    if not sys.stdin.isatty():
        parser.error("Run this script in an interactive terminal.")

    if args.robot:
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        node = rclpy.create_node("go2_keyboard_control")
    else:
        node = None

    input_fd = sys.stdin.fileno()
    settings = termios.tcgetattr(input_fd)
    try:
        if node is not None:
            publisher = node.create_publisher(Request, args.request_topic, 10)
            deadline = time.monotonic() + 5
            while publisher.get_subscription_count() == 0:
                if time.monotonic() >= deadline:
                    print(f"No compatible subscriber on {args.request_topic}.", file=sys.stderr)
                    return 1
                rclpy.spin_once(node, timeout_sec=0.1)
            send = publisher.publish
        else:
            def show(request):
                print(request.header.identity.api_id, request.parameter, flush=True)

            send = show
            print("Preview mode. Requests are printed locally.")

        print("1 StandUp | 2 BalanceStand | 3 StandDown | 4 Damp")
        print("W/S forward/back | A/D turn | Space stop | Q quit", flush=True)
        tty.setcbreak(input_fd)
        drive(send, input_fd, args.linear_speed)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(input_fd, termios.TCSADRAIN, settings)
        if node is not None:
            node.destroy_node()
            rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
