#!/usr/bin/env python3
"""Display and record two D435i videos on the PC over WiFi or wired SSH."""
import argparse
from datetime import datetime
from pathlib import Path
import queue
import shlex
import struct
import subprocess
import threading
import time

import cv2
import numpy as np


class StreamEnded(RuntimeError):
    pass


def read_exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            raise StreamEnded('Camera stream ended. See SSH/camera error above.')
        chunks.extend(part)
    return chunks


def record_stream(stream, output, latest, stop, stats, duration):
    writers = []
    try:
        version = read_exact(stream, 8)
        if version not in (b'GO2RGBD1', b'GO2RGBD2'):
            raise ValueError('Invalid camera stream header.')
        width, height, fps = struct.unpack('<III', read_exact(stream, 12))
        if (width, height, fps) != (640, 360, 15):
            raise ValueError('Unexpected camera stream dimensions/rate.')
        for name in ('rgb.mp4', 'depth.mp4'):
            writer = cv2.VideoWriter(str(output / name), cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
            writers.append(writer)
            if not writer.isOpened():
                raise RuntimeError(f'Could not open video encoder for {name}')
        started = None
        previous = -1
        while not stop.is_set():
            magic, sequence, rgb_size, depth_size = struct.unpack('<4sIII', read_exact(stream, 16))
            if magic != b'FRM1' or not all(0 < size <= width * height * 3
                                          for size in (rgb_size, depth_size)):
                raise ValueError('Invalid frame header.')
            if version == b'GO2RGBD1' and (rgb_size != width * height * 3 or depth_size != rgb_size):
                raise ValueError('Invalid raw frame size.')
            if sequence != previous + 1:
                raise ValueError('Unexpected frame sequence.')
            previous = sequence
            images = []
            for size in (rgb_size, depth_size):
                pixels = np.frombuffer(read_exact(stream, size), dtype=np.uint8)
                if version == b'GO2RGBD2':
                    image = cv2.imdecode(pixels, cv2.IMREAD_COLOR)
                    if image is None or image.shape != (height, width, 3):
                        raise ValueError('Invalid JPEG frame.')
                else:
                    image = cv2.cvtColor(pixels.reshape(height, width, 3), cv2.COLOR_RGB2BGR)
                images.append(image)
            # Record every received pair. Only the preview drops stale frames.
            for writer, image in zip(writers, images):
                writer.write(image)
            now = time.monotonic()
            if started is None:
                started = now
            stats['frames'] += 1
            stats['wire_bytes'] = stats.get('wire_bytes', 0) + rgb_size + depth_size + 16
            stats['last_frame'] = now
            stats['elapsed'] = now - started
            try:
                latest.get_nowait()
            except queue.Empty:
                pass
            latest.put_nowait(images)
            if duration and now - started >= duration:
                break
    finally:
        for writer in writers:
            writer.release()


def start_sender(host, control=None):
    # Source is sent through stdin; SSH authentication stays in the user's terminal.
    # The fixed remote directory contains only this capture utility.
    remote = r'''set -e
umask 077
mkdir -p "$HOME/.local/share/go2-rgbd"
cd "$HOME/.local/share/go2-rgbd"
cat > sender.cpp
if ! command -v g++ >/dev/null; then
  echo 'g++ is missing on the onboard computer.' >&2
  exit 1
fi
if command -v pkg-config >/dev/null && pkg-config --exists realsense2; then
  g++ -O2 -std=c++11 sender.cpp -o sender $(pkg-config --cflags --libs realsense2) -ljpeg
else
  g++ -O2 -std=c++11 sender.cpp -o sender -I/usr/local/include -L/usr/local/lib -Wl,-rpath,/usr/local/lib -lrealsense2 -ljpeg
fi
echo "SSH transport: $SSH_CONNECTION" >&2
exec ./sender
'''
    options = ['-S', str(control)] if control else []
    with Path(__file__).with_name('realsense_sender.cpp').open('rb') as source:
        return subprocess.Popen(
            ['ssh', *options, '-T', '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=5',
             '-o', 'ServerAliveCountMax=2', '--', host, 'bash -c ' + shlex.quote(remote)],
            stdin=source, stdout=subprocess.PIPE,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='unitree_go2', help='Onboard SSH alias or user@IP; use wireless IP for WiFi.')
    parser.add_argument('--ssh-control', type=Path, help='Explicit existing SSH control socket (uses that socket\'s transport).')
    parser.add_argument('--output', type=Path, help='New output directory; must not exist.')
    parser.add_argument('--duration', type=float, default=0, help='Record seconds, 0 until Q/Esc/Ctrl+C.')
    parser.add_argument('--no-display', action='store_true')
    args = parser.parse_args()
    if not np.isfinite(args.duration) or args.duration < 0:
        parser.error('--duration must be finite and nonnegative.')
    output = args.output or Path(__file__).resolve().parents[1] / 'recordings' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    print(f'Output: {output}\nRGB: rgb.mp4; depth visualization (0.2-5m): depth.mp4', flush=True)
    cv2.setNumThreads(1)
    process = start_sender(args.host, args.ssh_control)
    stop, latest, finished = threading.Event(), queue.Queue(maxsize=1), threading.Event()
    stats = {'frames': 0, 'last_frame': None, 'elapsed': 0}
    errors = []

    def receive():
        try:
            record_stream(process.stdout, output, latest, stop, stats, args.duration)
        except Exception as error:
            if not stop.is_set():
                errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=receive, daemon=True)
    worker.start()
    opened = False
    try:
        print('Enter SSH password locally if prompted. Q/Esc or Ctrl+C stops and saves both videos.', flush=True)
        next_report = time.monotonic() + 5
        report_time, report_frames, report_bytes = time.monotonic(), 0, 0
        while not finished.is_set():
            now = time.monotonic()
            if stats['last_frame'] is not None and now - stats['last_frame'] > 10:
                raise TimeoutError('No camera frames for 10 seconds.')
            if process.poll() is not None:
                # Let the worker drain buffered frames before reporting EOF.
                if finished.wait(0.1):
                    break
            if now >= next_report:
                frames, size = stats['frames'], stats.get('wire_bytes', 0)
                interval = now - report_time
                print(f'Recorded frame pairs: {frames}; received {(frames-report_frames)/interval:.1f} fps; '
                      f'{(size-report_bytes)*8/interval/1e6:.2f} Mbps', flush=True)
                report_time, report_frames, report_bytes = now, frames, size
                next_report = now + 5
            if not args.no_display:
                try:
                    images = latest.get(timeout=0.02)
                except queue.Empty:
                    images = None
                if images is not None:
                    if not opened:
                        for name in ('D435i RGB', 'D435i Depth (0.2-5m)'):
                            cv2.namedWindow(name, cv2.WINDOW_NORMAL)
                            cv2.resizeWindow(name, 640, 360)
                        opened = True
                    cv2.imshow('D435i RGB', images[0])
                    cv2.imshow('D435i Depth (0.2-5m)', images[1])
                if opened:
                    if cv2.waitKey(1) & 0xff in (27, ord('q')):
                        break
                    if any(cv2.getWindowProperty(name, cv2.WND_PROP_AUTOSIZE) < 0
                           for name in ('D435i RGB', 'D435i Depth (0.2-5m)')):
                        break
            else:
                finished.wait(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        worker.join(timeout=5)
        if worker.is_alive():
            raise RuntimeError('Video writer did not finish closing.')
        process.stdout.close()
        cv2.destroyAllWindows()
        print(f'Saved {stats["frames"]} paired frames to {output}', flush=True)
    if errors:
        raise SystemExit(str(errors[0]))
    if not stats['frames']:
        raise SystemExit('No camera frames recorded.')


if __name__ == '__main__':
    main()
