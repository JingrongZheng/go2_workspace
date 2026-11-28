"""Shared WebRTC PCM output for dialogue. No standalone playback or training CLI."""
from __future__ import annotations

import asyncio
import getpass
import json
import socket
import sys
import time
from fractions import Fraction
from typing import Optional
from unittest.mock import patch

import numpy as np

VUI_API_SET_VOLUME = 1003
WEBRTC_STREAM_RATE = 48000
WEBRTC_FRAME_SAMPLES = 960

def create_webrtc_connection(args):
    from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod

    if not args.remote:
        return UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=args.ip)
    if not sys.stdin.isatty():
        raise ValueError("Run --remote in an interactive terminal to enter the Unitree password securely.")
    username = args.username or input("Unitree App bound account email: ").strip()
    if not username or "@" not in username:
        raise ValueError("Remote mode requires an email/password account.")
    password = getpass.getpass("Unitree App password (hidden, not saved): ")
    if not password:
        raise ValueError("Password cannot be empty.")
    conn = UnitreeWebRTCConnection(
        WebRTCConnectionMethod.Remote,
        serialNumber=args.sn,
        username=username,
        password=password,
        region=args.region,
        device_type="Go2",
    )
    if not conn.token:
        raise RuntimeError("Unitree cloud login failed. Check account email, password, and --region.")
    return conn

async def connect_webrtc(conn, args):
    if args.remote:
        await asyncio.wait_for(conn.connect(), timeout=60)
        print("WebRTC connected (Remote mode).", flush=True)
        return
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route_sock:
        route_sock.connect((args.ip, 9991))
        local_ip = args.local_ip or route_sock.getsockname()[0]
    with patch("aioice.ice.get_host_addresses", return_value=[local_ip]):
        await asyncio.wait_for(conn.connect(), timeout=30)
    print(f"WebRTC connected to {args.ip} (local ICE: {local_ip}).", flush=True)

async def set_go2_volume(conn, volume: int) -> None:
    if not (0 <= volume <= 10):
        raise ValueError("Go2 VUI volume must be an integer between 0 and 10.")
    resp = await conn.datachannel.pub_sub.publish_request_new(
        "rt/api/vui/request",
        {
            "api_id": VUI_API_SET_VOLUME,
            "parameter": json.dumps({"volume": volume}),
        },
    )
    print(f"Set Go2 VUI volume -> {volume}/10 (resp={resp})", flush=True)

def make_live_audio_track():
    """Create a 48 kHz mono AudioStreamTrack that plays queued int16 PCM frames in real time."""
    import av
    from aiortc import AudioStreamTrack

    class QueuedPcmAudioTrack(AudioStreamTrack):
        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue()
            self._pts = 0
            self._start_time: Optional[float] = None
            self._idle_event = asyncio.Event()
            self._idle_event.set()

        def enqueue_pcm48k(self, pcm_i16: np.ndarray) -> None:
            pcm_i16 = np.asarray(pcm_i16, dtype=np.int16).reshape(-1)
            if len(pcm_i16) == 0:
                return
            self._idle_event.clear()
            rem = len(pcm_i16) % WEBRTC_FRAME_SAMPLES
            if rem:
                pcm_i16 = np.concatenate(
                    [pcm_i16, np.zeros(WEBRTC_FRAME_SAMPLES - rem, dtype=np.int16)]
                )
            for offset in range(0, len(pcm_i16), WEBRTC_FRAME_SAMPLES):
                self._queue.put_nowait(pcm_i16[offset : offset + WEBRTC_FRAME_SAMPLES])

        def enqueue_silence(self, seconds: float) -> None:
            n = int(round(max(0.0, seconds) * WEBRTC_STREAM_RATE))
            if n > 0:
                self.enqueue_pcm48k(np.zeros(n, dtype=np.int16))

        async def wait_drained(self) -> None:
            await self._idle_event.wait()

        async def recv(self):
            if self._start_time is None:
                self._start_time = time.monotonic()
            else:
                target_time = self._start_time + (self._pts / float(WEBRTC_STREAM_RATE))
                delay = target_time - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)

            try:
                samples = self._queue.get_nowait()
                if self._queue.empty():
                    self._idle_event.set()
            except asyncio.QueueEmpty:
                samples = np.zeros(WEBRTC_FRAME_SAMPLES, dtype=np.int16)
                self._idle_event.set()

            frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = WEBRTC_STREAM_RATE
            frame.pts = self._pts
            frame.time_base = Fraction(1, WEBRTC_STREAM_RATE)
            self._pts += WEBRTC_FRAME_SAMPLES
            return frame

    return QueuedPcmAudioTrack()

class StreamingPcmResampler:
    """Band-limited PCM conversion preserving filter state across network chunks."""
    def __init__(self, src_rate, dst_rate=48000):
        import av
        self.src_rate = src_rate
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=dst_rate)
        self._pending = b""
        self._pts = 0

    def push(self, data):
        import av
        self._pending += data
        length = len(self._pending) // 2 * 2
        if not length:
            return np.empty(0, dtype=np.int16)
        raw, self._pending = self._pending[:length], self._pending[length:]
        frame = av.AudioFrame.from_ndarray(np.frombuffer(raw, dtype="<i2").reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = self.src_rate
        frame.pts = self._pts
        frame.time_base = Fraction(1, self.src_rate)
        self._pts += length // 2
        return self._collect(self._resampler.resample(frame))

    def flush(self):
        if self._pending:
            raise RuntimeError("TTS returned a truncated PCM sample.")
        return self._collect(self._resampler.resample(None))

    @staticmethod
    def _collect(frames):
        arrays = [frame.to_ndarray().reshape(-1) for frame in frames]
        return np.concatenate(arrays) if arrays else np.empty(0, dtype=np.int16)

async def attach_stream_track(conn, warmup_sec: float):
    track = make_live_audio_track()
    audio_transceiver = next(
        (t for t in conn.pc.getTransceivers() if t.kind == "audio"),
        None,
    )
    if audio_transceiver is not None and audio_transceiver.sender is not None:
        audio_transceiver.sender.replaceTrack(track)
    else:
        conn.pc.addTrack(track)
    conn.audio.switchAudioChannel(True)
    if warmup_sec > 0:
        print(f"[stream] Warming up Go2 WebRTC audio channel ({warmup_sec:.1f}s)...", flush=True)
        track.enqueue_silence(warmup_sec)
        await track.wait_drained()
    return track
