#!/usr/bin/env python3
"""Text -> OpenAI-compatible streaming chat -> streaming iFlytek TTS -> Go2 audio.

No microphone, tools, or motion control. Credentials stay in .work/dialogue.env.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
from async_compat import aclosing
import json
import os
import sys
import time
from pathlib import Path

import aiohttp
import numpy as np

from xfyun_tts import find_workspace_root, load_env_file, resolve_xfyun_config, validate_config
from xfyun_duplex import stream_text_pcm, stream_sentence_pcm
from webrtc_audio import (attach_stream_track, connect_webrtc, create_webrtc_connection,
                            StreamingPcmResampler, set_go2_volume)

DEFAULT_SYSTEM = ('你是机器狗 Go2 的中文语音助手。请自然、简短地回答，通常一到三句话。'
                  '使用适合直接朗读的纯文本，不使用 Markdown。你目前只能对话，不能执行移动或其他实体操作。')


async def stream_reply(session, base_url, key, model, messages, timeout=60,
                       reasoning_effort=None, assistant_state=None):
    """Consume SSE events, preserving UTF-8 and multiline event boundaries."""
    url = base_url.rstrip('/')
    if not url.endswith('/chat/completions'):
        url += '/chat/completions'
    headers = {'Authorization': f'Bearer {key}', 'Accept': 'text/event-stream'}
    body = {'model': model, 'messages': messages, 'stream': True}
    if reasoning_effort:
        body['reasoning_effort'] = reasoning_effort
    if assistant_state is not None:
        assistant_state.update(role='assistant', content='', reasoning_content='')
    async with session.post(url, headers=headers,
                            json=body,
                            timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=timeout)) as resp:
        if resp.status != 200:
            # Do not echo provider bodies or URLs: these may contain secrets.
            raise RuntimeError(f'LLM HTTP {resp.status}; check model, endpoint and API key.')
        if 'text/event-stream' not in resp.headers.get('Content-Type', ''):
            raise RuntimeError('LLM endpoint did not return SSE; enable streaming support.')
        lines = []
        finished = False
        async for raw in resp.content:
            line = raw.decode('utf-8').rstrip('\r\n')
            if line.startswith('data:'):
                lines.append(line[5:].lstrip(' '))
            if line or not lines:
                continue
            data, lines = '\n'.join(lines), []
            if data == '[DONE]':
                if not finished:
                    raise RuntimeError('LLM stream ended without a finish_reason.')
                return
            event = json.loads(data)
            if 'error' in event:
                raise RuntimeError('LLM returned a streaming error.')
            for choice in event.get('choices', []):
                if choice.get('index', 0) != 0:
                    continue
                delta = choice.get('delta', {})
                # reasoning_content and tool calls are intentionally never spoken.
                if assistant_state is not None:
                    reasoning = delta.get('reasoning_content')
                    if isinstance(reasoning, str):
                        assistant_state['reasoning_content'] += reasoning
                content = delta.get('content')
                if isinstance(content, str) and content:
                    if assistant_state is not None:
                        assistant_state['content'] += content
                    yield content
                reason = choice.get('finish_reason')
                if reason:
                    if reason != 'stop':
                        raise RuntimeError(f'LLM reply incomplete (finish_reason={reason}).')
                    finished = True
        if not finished or lines:
            raise RuntimeError('LLM SSE connection closed before completion.')


class RobotSink:
    def __init__(self, track, sample_rate):
        self.track = track
        self.resampler = StreamingPcmResampler(sample_rate, 48000)
        self.pending = np.empty(0, dtype=np.int16)

    async def _emit(self, samples, final=False):
        if len(samples):
            self.pending = np.concatenate([self.pending, samples])
        while len(self.pending) >= 960 or (final and len(self.pending)):
            frame, self.pending = self.pending[:960], self.pending[960:]
            deadline = time.monotonic() + 15
            while self.track._queue.qsize() >= 100:
                if time.monotonic() > deadline:
                    raise TimeoutError('Go2 audio consumer stopped draining.')
                await asyncio.sleep(.02)
            self.track.enqueue_pcm48k(frame)

    async def write(self, chunk):
        await self._emit(self.resampler.push(chunk))

    async def finish(self):
        # Flush filter delay, padding only the final 20ms frame of the whole turn.
        await self._emit(self.resampler.flush(), final=True)
        self.track.enqueue_silence(.1)
        await asyncio.wait_for(self.track.wait_drained(), timeout=15)


class LocalSink:
    def __init__(self, proc):
        self.proc = proc

    async def write(self, chunk):
        self.proc.stdin.write(chunk)
        await self.proc.stdin.drain()

    async def finish(self):
        self.proc.stdin.close()
        if await self.proc.wait():
            raise RuntimeError('Local audio player failed.')


async def run_turn(text_source, cfg, sink, tts_mode="sentences", on_text=None, quiet=False):
    """Pull reply deltas while a separate WS receiver delivers PCM to the sink."""
    started = time.monotonic()
    reply = []
    metrics = {}

    async def texts():
        async for delta in text_source:
            metrics.setdefault('first_text_ms', round((time.monotonic() - started) * 1000))
            if not quiet:
                print(delta, end='', flush=True)
            if on_text is not None:
                on_text(delta)
            reply.append(delta)
            yield delta
        metrics['llm_done_ms'] = round((time.monotonic() - started) * 1000)
        if not reply:
            raise RuntimeError('LLM returned no spoken reply.')

    if not quiet:
        print('Go2> ', end='', flush=True)
    if sink is None:
        async for _ in texts():
            pass
    else:
        synthesize = stream_text_pcm if tts_mode == "duplex" else stream_sentence_pcm
        async with aclosing(synthesize(cfg, texts())) as audio:
            async for pcm in audio:
                metrics.setdefault('first_audio_ms', round((time.monotonic() - started) * 1000))
                await sink.write(pcm)
        if 'first_audio_ms' not in metrics:
            raise RuntimeError('TTS returned no audio.')
        await sink.finish()
    metrics['done_ms'] = round((time.monotonic() - started) * 1000)
    if not quiet:
        print('\n[timing] ' + json.dumps(metrics), flush=True)
    return ''.join(reply), metrics


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--init-env', action='store_true')
    p.add_argument('--llm-env', type=Path, default=find_workspace_root() / '.work/dialogue.env')
    p.add_argument('--base-url')
    p.add_argument('--model')
    p.add_argument('--reasoning-effort', choices=['low', 'high', 'max'],
                   help='Kimi K3 thinking cannot be disabled; use low for conversation.')
    p.add_argument('--system', default=DEFAULT_SYSTEM)
    p.add_argument('--text', help='One turn; otherwise an interactive multi-turn conversation.')
    target = p.add_mutually_exclusive_group()
    target.add_argument('--local-preview', action='store_true', help='Stream PCM directly to PC paplay.')
    target.add_argument('--no-audio', action='store_true', help='LLM-only diagnostic.')
    p.add_argument('--ip')
    p.add_argument('--local-ip')
    p.add_argument('--remote', action='store_true')
    p.add_argument('--sn')
    p.add_argument('--username')
    p.add_argument('--region', choices=['cn', 'global'], default='cn')
    p.add_argument('--voice', default='mambo')
    p.add_argument('--tts-mode', choices=['sentences', 'duplex'], default='sentences',
                   help='Short-clause audio streaming (default), or experimental single-session duplex.')
    p.add_argument('--env-file', type=Path, help='iFlytek env file')
    p.add_argument('--volume', type=int, choices=range(11))
    p.add_argument('--no-dup-first-char', action='store_true')
    p.add_argument('--history-turns', type=int, default=10)
    a = p.parse_args(argv)
    if a.history_turns < 1:
        p.error('--history-turns must be >= 1')
    if not (a.init_env or a.local_preview or a.no_audio):
        if a.remote and not a.sn:
            p.error('--remote requires --sn')
        if not a.remote and not a.ip:
            p.error('Provide --ip, --remote --sn, --local-preview or --no-audio')
    return a


async def run(args):
    if args.init_env:
        args.llm_env.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create: never overwrite an existing credential file.
        fd = os.open(args.llm_env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write('# Kimi Chat Completions endpoint\nLLM_BASE_URL=https://api.moonshot.cn/v1\nLLM_MODEL=kimi-k3.1-pro\nLLM_REASONING_EFFORT=low\nLLM_API_KEY=\n')
        print(f'Edit {args.llm_env}')
        return
    env = load_env_file(args.llm_env)
    def pick(name):
        return os.environ.get(name) or env.get(name, '')
    base_url, model, key = args.base_url or pick('LLM_BASE_URL'), args.model or pick('LLM_MODEL'), pick('LLM_API_KEY')
    if not all([base_url, model, key]):
        raise ValueError(f'Set LLM_BASE_URL, LLM_MODEL, LLM_API_KEY in {args.llm_env}')
    effort = args.reasoning_effort or pick('LLM_REASONING_EFFORT') or ('low' if 'kimi-k3' in model else None)
    if effort and effort not in ('low', 'high', 'max'):
        raise ValueError('LLM_REASONING_EFFORT must be low, high or max')
    cfg = None
    if not args.no_audio:
        cfg = resolve_xfyun_config(env_file=args.env_file, voice=args.voice,
                                   dup_first_char=not args.no_dup_first_char)
        validate_config(cfg)
        if cfg.engine != 'clone':
            raise ValueError('Duplex dialogue requires iFlytek clone engine.')
    conn, track, proc = None, None, None
    history = []
    try:
        if not (args.local_preview or args.no_audio):
            conn = create_webrtc_connection(args)
            await connect_webrtc(conn, args)
            if args.volume is not None:
                await set_go2_volume(conn, args.volume)
            track = await attach_stream_track(conn, 1.5)
        async with aiohttp.ClientSession(trust_env=True) as session:
            while True:
                if args.text is not None:
                    line = args.text.strip()
                else:
                    try:
                        line = (await asyncio.get_running_loop().run_in_executor(None, input, 'You> ')).strip()
                    except EOFError:
                        break
                    if line.lower() in ('/quit', '/exit'):
                        break
                    if line == '/reset':
                        history.clear()
                        print('Conversation reset.')
                        continue
                if not line:
                    if args.text is not None:
                        break
                    continue
                messages = [{'role': 'system', 'content': args.system}] + history + [{'role': 'user', 'content': line}]
                sink = None
                if args.local_preview:
                    proc = await asyncio.create_subprocess_exec('paplay', '--raw', '--format=s16le',
                        f'--rate={cfg.sample_rate}', '--channels=1', stdin=asyncio.subprocess.PIPE)
                    sink = LocalSink(proc)
                elif track:
                    sink = RobotSink(track, cfg.sample_rate)
                assistant_state = {}
                source = stream_reply(session, base_url, key, model, messages,
                                      reasoning_effort=effort, assistant_state=assistant_state)
                async with aclosing(source):
                    reply, _ = await run_turn(source, cfg, sink, args.tts_mode)
                # Kimi Preserved Thinking requires reasoning to be returned in history.
                # It remains in memory only; it is never displayed or synthesized.
                if not assistant_state.get('reasoning_content'):
                    assistant_state.pop('reasoning_content', None)
                history.extend([{'role': 'user', 'content': line}, assistant_state])
                history = history[-args.history_turns * 2:]
                if args.text is not None:
                    break
    finally:
        if proc and proc.returncode is None:
            proc.terminate()
            await proc.wait()
        if track:
            track.stop()
        if conn:
            with contextlib.suppress(Exception):
                conn.audio.switchAudioChannel(False)
            await conn.disconnect()


def main():
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        print('\nStopped.')
    except Exception as exc:
        # Avoid printing authenticated WS URLs / API keys from library exceptions.
        print(f'Dialogue failed ({type(exc).__name__}). Check configuration/network; conversation stopped.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
