"""Offline two-video protocol/encoder check; no camera or SSH connection."""
import importlib.util
import io
from pathlib import Path
import queue
import struct
import tempfile
import threading
import cv2
import numpy as np

path = Path(__file__).resolve().parents[2] / 'shared/record_realsense.py'
spec = importlib.util.spec_from_file_location('record_realsense', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
width, height, fps = 640, 360, 15
rgb = np.zeros((height, width, 3), np.uint8)
rgb[:, :] = (220, 30, 10)
depth = np.zeros_like(rgb)
depth[:, :] = (10, 30, 220)
size = rgb.nbytes
payload = b'GO2RGBD1' + struct.pack('<III', width, height, fps)
for sequence in range(30):
    payload += struct.pack('<4sIII', b'FRM1', sequence, size, size) + rgb.tobytes() + depth.tobytes()
with tempfile.TemporaryDirectory(prefix='go2-two-video-') as directory:
    output = Path(directory)
    stats = {'frames': 0}
    try:
        m.record_stream(io.BytesIO(payload), output, queue.Queue(maxsize=1), threading.Event(), stats, 0)
    except m.StreamEnded:
        pass
    assert stats['frames'] == 30
    assert sorted(p.name for p in output.iterdir()) == ['depth.mp4', 'rgb.mp4']
    for name, expected in [('rgb.mp4', (10, 30, 220)), ('depth.mp4', (220, 30, 10))]:
        capture = cv2.VideoCapture(str(output / name))
        assert capture.isOpened()
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 30
        assert capture.get(cv2.CAP_PROP_FPS) == 15
        count = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            assert frame.shape == (360, 640, 3)
            assert np.max(np.abs(frame[100,100].astype(float) - expected)) < 15
            count += 1
        assert count == 30
        capture.release()
    print('PASS: exactly two playable MP4 videos, 30 paired frames, 640x360@15, RGB channel order, EOF finalization.')
try:
    m.read_exact(io.BytesIO(b'abc'), 4)
except m.StreamEnded:
    print('PASS: truncated stream is detected.')
else:
    raise AssertionError('truncated input accepted')
