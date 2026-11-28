#!/usr/bin/env python3
"""Run on the robot computer. Accept text jobs; own LLM, TTS, history and playback.

Loopback-only HTTP, accessed through SSH. Accepted jobs keep running if the
submitting PC disconnects. No speech recognition or motion APIs.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import uuid
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import aiohttp
from aiohttp import web

from async_compat import aclosing
from streaming_dialogue import (DEFAULT_SYSTEM, RobotSink, run_turn, stream_reply,
                                attach_stream_track, connect_webrtc,
                                create_webrtc_connection, set_go2_volume)
from xfyun_tts import find_workspace_root, load_env_file, resolve_xfyun_config, validate_config


class OnboardDialogue:
    def __init__(self, args):
        self.args = args
        self.history = []
        self.jobs = OrderedDict()
        self.active = None
        self.conn = None
        self.track = None
        self.client = None
        self.base = self.model = self.key = ''
        self.cfg = None
        self.config_ready = False
        self.cloud_verified = False
        self.config_problem = 'not_loaded'

    async def start(self, app):
        self.client = aiohttp.ClientSession(trust_env=True)
        self.reload_config()

    def reload_config(self):
        env = load_env_file(self.args.llm_env)
        def pick(key, default=''):
            return os.environ.get(key) or env.get(key, default)
        self.base = pick('LLM_BASE_URL', 'https://api.moonshot.cn/v1')
        self.model = pick('LLM_MODEL', 'kimi-k3.1-pro')
        self.key = pick('LLM_API_KEY')
        self.effort = pick('LLM_REASONING_EFFORT', 'low')
        self.config_ready = False
        if not self.key:
            self.config_problem = 'missing_llm_key'
            return
        if self.effort not in ('low', 'high', 'max'):
            self.config_problem = 'invalid_reasoning_effort'
            return
        if not self.args.no_audio:
            try:
                self.cfg = resolve_xfyun_config(env_file=self.args.env_file, voice=self.args.voice)
                validate_config(self.cfg)
            except (ValueError, OSError):
                self.config_problem = 'invalid_tts_config'
                return
        self.config_problem = None
        self.config_ready = True

    async def disconnect(self):
        if self.track:
            self.track.stop()
            self.track = None
        if self.conn:
            conn, self.conn = self.conn, None
            with contextlib.suppress(Exception):
                conn.audio.switchAudioChannel(False)
            with contextlib.suppress(Exception):
                await conn.disconnect()

    async def close(self, app):
        if self.active and not self.active.done():
            self.active.cancel()
            await asyncio.gather(self.active, return_exceptions=True)
        await self.disconnect()
        await self.client.close()

    async def ensure_speaker(self):
        if self.track and self.conn and self.conn.isConnected:
            return
        await self.disconnect()
        opts = SimpleNamespace(remote=False, ip=self.args.speaker_ip, local_ip=None)
        self.conn = create_webrtc_connection(opts)
        await connect_webrtc(self.conn, opts)
        if self.args.volume is not None:
            await set_go2_volume(self.conn, self.args.volume)
        self.track = await attach_stream_track(self.conn, 1.5)

    async def execute(self, job_id, text):
        job = self.jobs[job_id]
        job['status'] = 'running'
        try:
            if not self.args.no_audio:
                await self.ensure_speaker()
            state = {}
            messages = [{'role': 'system', 'content': DEFAULT_SYSTEM}] + self.history + [{'role': 'user', 'content': text}]
            source = stream_reply(self.client, self.base, self.key, self.model, messages,
                                  reasoning_effort=self.effort, assistant_state=state)
            def update(delta):
                job['reply'] += delta
            sink = None if self.args.no_audio else RobotSink(self.track, self.cfg.sample_rate)
            async with aclosing(source):
                _, metrics = await run_turn(source, self.cfg, sink, self.args.tts_mode,
                                            on_text=update, quiet=True)
            self.history.extend([{'role': 'user', 'content': text}, state])
            self.history = self.history[-self.args.history_turns * 2:]
            job.update(status='done', metrics=metrics)
            self.cloud_verified = True
        except asyncio.CancelledError:
            job.update(status='cancelled')
            raise
        except Exception as exc:
            # Avoid exception text, HTTP response bodies or signed URLs in logs/API.
            job.update(status='failed', error=type(exc).__name__)
            await self.disconnect()

    async def health(self, request):
        if not self.active or self.active.done():
            self.reload_config()
        return web.json_response({'service': 'go2-onboard-dialogue',
            'runs_on': 'robot_computer', 'config_ready': self.config_ready,
            'config_problem': self.config_problem,
            'busy': bool(self.active and not self.active.done()),
            'audio_enabled': not self.args.no_audio, 'cloud_connectivity_verified': self.cloud_verified})

    async def ask(self, request):
        if self.active and not self.active.done():
            raise web.HTTPConflict(text='Robot is already replying.')
        self.reload_config()
        if not self.config_ready:
            return web.json_response({'error': self.config_problem}, status=503)
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest(text='Expected JSON object with text.')
        if not isinstance(body, dict) or not isinstance(body.get('text'), str):
            raise web.HTTPBadRequest(text='Expected JSON object with text.')
        text = body['text'].strip()
        if not text or len(text) > 4000:
            raise web.HTTPBadRequest(text='Text must contain 1..4000 characters.')
        job_id = uuid.uuid4().hex
        while len(self.jobs) >= 32:
            self.jobs.popitem(last=False)
        self.jobs[job_id] = {'id': job_id, 'status': 'accepted', 'reply': ''}
        # No request/client reference in task: reply survives a PC disconnection.
        self.active = asyncio.create_task(self.execute(job_id, text))
        return web.json_response({'id': job_id, 'status': 'accepted'}, status=202)

    async def job(self, request):
        job = self.jobs.get(request.match_info['job_id'])
        if job is None:
            raise web.HTTPNotFound()
        return web.json_response(job)

    async def reset(self, request):
        if self.active and not self.active.done():
            raise web.HTTPConflict(text='Wait until robot finishes replying.')
        self.history.clear()
        self.jobs.clear()
        return web.json_response({'status': 'reset'})


def make_app(service):
    app = web.Application(client_max_size=32 * 1024)
    app.router.add_get('/health', service.health)
    app.router.add_post('/ask', service.ask)
    app.router.add_get('/jobs/{job_id}', service.job)
    app.router.add_post('/reset', service.reset)
    app.on_startup.append(service.start)
    app.on_cleanup.append(service.close)
    return app


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--speaker-ip', default='192.168.123.161', help='Internal Go2 mainboard, not robot-computer .18')
    p.add_argument('--voice', default='mambo')
    p.add_argument('--volume', type=int, choices=range(11))
    p.add_argument('--llm-env', type=Path, default=find_workspace_root() / '.work/dialogue.env')
    p.add_argument('--env-file', type=Path, default=find_workspace_root() / '.work/xfyun.env')
    p.add_argument('--tts-mode', choices=['sentences', 'duplex'], default='sentences')
    p.add_argument('--history-turns', type=int, default=10)
    p.add_argument('--no-audio', action='store_true', help='Diagnostic only, no connection to speaker')
    args = p.parse_args()
    if args.history_turns < 1:
        p.error('--history-turns must be >= 1')
    web.run_app(make_app(OnboardDialogue(args)), host='127.0.0.1', port=args.port,
                access_log=None, print=lambda _: None)


if __name__ == '__main__':
    main()
