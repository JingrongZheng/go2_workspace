#!/usr/bin/env python3
"""Dedicated emergency stop & BalanceStand terminal over Go2 SSH control link.

Reuses the already-deployed onboard go2_wifi_control_source.py receiver (no onboard
changes required). Connects pre-armed and sends zero commands until a key is pressed.
"""
import argparse
import ipaddress
import json
import os
import select
import shlex
import struct
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESTOP_LOCK = ROOT / ".work/estop.lock"
CLOCK_REPLY = struct.Struct("!q")

BALANCE_STAND = 1002
STOP_MOVE = 1003
STAND_UP = 1004
STAND_DOWN = 1005
HOLD_INTERVAL_S = 0.2  # 5 Hz override while Hold-Stop is latched


def remote_command(check=False, dry=False):
    xml = "<CycloneDDS><Domain><General><NetworkInterfaceAddress>eth10</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
    setup = (
        "set -e\n"
        "source /opt/ros/foxy/setup.bash >&2\n"
        "source ~/cyclonedds_ws/install/local_setup.bash >&2\n"
        "source ~/go2-keyboard-control/ws/install/local_setup.bash >&2\n"
        "export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp PYTHONNOUSERSITE=1\n"
        f"export CYCLONEDDS_URI={shlex.quote(xml)}\n"
        "exec /usr/bin/python3 ~/go2-keyboard-control/go2_wifi_control_source.py"
    )
    return setup + (" --check" if check else "") + (" --dry-run" if dry else "")


def read_exact(stream, size, timeout=8.0):
    data = bytearray()
    fd = stream.fileno()
    deadline = time.monotonic() + timeout
    while len(data) < size:
        if not select.select([fd], [], [], max(0.0, deadline - time.monotonic()))[0]:
            raise TimeoutError("Timed out waiting for onboard control receiver")
        chunk = os.read(fd, size - len(data))
        if not chunk:
            raise RuntimeError("Onboard control receiver disconnected during handshake")
        data.extend(chunk)
    return bytes(data)


def measure_pc_minus_dock(process):
    samples = []
    for attempt in range(9):
        start_mono = time.monotonic_ns()
        start = time.time_ns()
        process.stdin.write(b"T")
        process.stdin.flush()
        dock, = CLOCK_REPLY.unpack(read_exact(process.stdout, CLOCK_REPLY.size, timeout=40.0 if not attempt else 8.0))
        end = time.time_ns()
        rtt = time.monotonic_ns() - start_mono
        if abs(end - start - rtt) < 5_000_000:
            samples.append((rtt, (start + end) // 2 - dock))
    if not samples:
        raise RuntimeError("PC clock changed during calibration; retry estop")
    _, offset = min(samples)
    return offset


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", type=ipaddress.IPv4Address, default="192.168.123.18")
    p.add_argument("--socket", type=Path, default=ROOT / ".work/ssh-control/go2.sock")
    p.add_argument("--check", action="store_true", help="Read-only check of onboard sport subscriber")
    p.add_argument("--robot", action="store_true", help="Arm live robot E-Stop / BalanceStand publishing")
    args = p.parse_args()

    if not args.check and not sys.stdin.isatty():
        p.error("Use an interactive PC terminal")

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
    settings = None
    try:
        offset = measure_pc_minus_dock(proc)
        proc.stdin.write(b"S" + struct.pack("!q", offset))
        proc.stdin.flush()
        if not select.select([proc.stdout], [], [], 8)[0]:
            raise TimeoutError("Onboard control receiver did not become ready")
        status = json.loads(proc.stdout.readline())
        if not status.get("ready"):
            raise RuntimeError(status.get("error", "Onboard receiver failed"))

        mode_banner = (
            "=== LIVE E-STOP ARMED (will publish to /api/sport/request on keypress) ==="
            if args.robot else
            "=== PREVIEW MODE (dry-run; no real robot requests will be published) ==="
        )
        print(mode_banner)
        print("  [Space / Enter]  E-STOP + LOCK: cuts off cmd-bridge immediately & holds StopMove + BalanceStand")
        print("  [1]              StandUp (1004, smooth stand up)")
        print("  [2]              StopMove + BalanceStand (1002)")
        print("  [3]              StandDown (1005, smooth lie down) + lock cmd-bridge")
        print("  [R]              Release E-STOP lock (allow cmd-bridge again)")
        print("  [Q]              Quit cleanly (keeps lock if currently latched)", flush=True)

        os.set_blocking(proc.stdin.fileno(), False)

        def engage_lock(reason: str):
            ESTOP_LOCK.parent.mkdir(parents=True, exist_ok=True)
            ESTOP_LOCK.write_text(f"{reason} {time.time():.3f}\n")

        def release_lock():
            try:
                ESTOP_LOCK.unlink()
            except FileNotFoundError:
                pass

        def send_api(api_id):
            data = (json.dumps({"api_id": api_id, "parameter": "", "sent_pc_ns": time.time_ns()}) + "\n").encode()
            if os.write(proc.stdin.fileno(), data) != len(data):
                raise ConnectionError("Partial control write to SSH pipe")

        fd = sys.stdin.fileno()
        settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)

        holding = False
        next_hold = 0.0
        hold_count = 0

        while True:
            ready, _, _ = select.select([fd], [], [], 0.05)
            now = time.monotonic()
            if ready:
                key = os.read(fd, 1).decode("ascii", errors="ignore").lower()
                if key in ("q", ""):
                    print("\nExiting E-Stop terminal.", flush=True)
                    return 0
                if key in (" ", "\r", "\n"):
                    engage_lock("estop_hold")
                    send_api(STOP_MOVE)
                    send_api(BALANCE_STAND)
                    holding = True
                    hold_count = 1
                    next_hold = now + HOLD_INTERVAL_S
                    print("[E-STOP] LOCKED! cmd-bridge blocked; holding StopMove + BalanceStand (press R to release)", flush=True)
                elif key == "1":
                    holding = False
                    send_api(STAND_UP)
                    print("[E-STOP] Sent smooth StandUp (1004)", flush=True)
                elif key == "2":
                    holding = False
                    send_api(STOP_MOVE)
                    send_api(BALANCE_STAND)
                    print("[E-STOP] Sent StopMove + BalanceStand (1002)", flush=True)
                elif key == "3":
                    engage_lock("stand_down")
                    holding = False
                    send_api(STOP_MOVE)
                    time.sleep(0.15)
                    send_api(STAND_DOWN)
                    print("[E-STOP] LOCKED + Sent smooth StandDown (1005)", flush=True)
                elif key == "r":
                    holding = False
                    release_lock()
                    print(f"[E-STOP] Released lock (after {hold_count} pulses); cmd-bridge allowed again.", flush=True)

            if holding and now >= next_hold:
                send_api(STOP_MOVE)
                send_api(BALANCE_STAND)
                hold_count += 1
                next_hold = now + HOLD_INTERVAL_S
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        if settings is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, settings)
        if proc.stdin is not None:
            proc.stdin.close()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
