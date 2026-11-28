"""iFlytek clone: concurrent text input and PCM output in one WebSocket session.

Protocol: https://www.xfyun.cn/doc/spark/reproduction.html
"""
import asyncio
import base64
import contextlib
from async_compat import aclosing
import json

import aiohttp

from xfyun_tts import build_clone_request, build_signed_ws_url, preprocess_tts_text, validate_config


async def stream_text_pcm(cfg, text_source, timeout=60):
    validate_config(cfg)
    if cfg.engine != 'clone':
        raise ValueError('Duplex streaming requires the clone engine.')
    url = build_signed_ws_url(cfg.resolved_url(), cfg.api_key, cfg.api_secret)
    events = asyncio.Queue(maxsize=16)
    client_timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=timeout)
    async with aiohttp.ClientSession(timeout=client_timeout, trust_env=True) as session:
        async with session.ws_connect(url, max_msg_size=16 * 1024 * 1024) as ws:
            async def send():
                seq = 0
                async with aclosing(text_source):
                    async for delta in text_source:
                        # Keep each base64 payload well below the documented 8000 byte cap.
                        for offset in range(0, len(delta), 500):
                            part = delta[offset:offset + 500]
                            if not part.strip() and seq == 0:
                                continue
                            if seq == 0:
                                part = preprocess_tts_text(cfg, part)
                            request = build_clone_request(cfg, part)
                            request['header']['status'] = 0 if seq == 0 else 1
                            request['payload']['text'].update(status=0 if seq == 0 else 1, seq=seq)
                            await ws.send_json(request)
                            seq += 1
                if seq == 0:
                    raise RuntimeError('No text to synthesize.')
                request = build_clone_request(cfg, '')
                request['header']['status'] = 2
                request['payload']['text'].update(status=2, seq=seq)
                await ws.send_json(request)

            async def receive():
                while True:
                    msg = await ws.receive(timeout=timeout)
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        if msg.type in (aiohttp.WSMsgType.PING, aiohttp.WSMsgType.PONG):
                            continue
                        raise RuntimeError('TTS socket closed before final audio frame.')
                    data = json.loads(msg.data)
                    header = data.get('header', {})
                    if header.get('code', -1) != 0:
                        raise RuntimeError(f"TTS service error code {header.get('code')}")
                    audio = data.get('payload', {}).get('audio', {})
                    if audio.get('audio'):
                        await events.put(base64.b64decode(audio['audio'], validate=True))
                    if audio.get('status', header.get('status')) == 2:
                        return

            async def supervise():
                tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
                try:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                    # Receiver finishing while text is still being sent indicates truncation.
                    if tasks[1] in done and not tasks[0].done():
                        raise RuntimeError('TTS ended before text input completed.')
                    await asyncio.gather(*pending)
                except Exception as exc:
                    await events.put(exc)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                await events.put(None)

            supervisor = asyncio.create_task(supervise())
            try:
                while True:
                    item = await events.get()
                    if item is None:
                        return
                    if isinstance(item, Exception):
                        raise item
                    yield item
            finally:
                supervisor.cancel()
                await asyncio.gather(supervisor, return_exceptions=True)


async def stream_sentence_pcm(cfg, text_source, timeout=60):
    """Synthesize short clauses as soon as available; overlap LLM with TTS.

    Keeps the proven single-text/audio-stream protocol as a compatibility path
    when a clone service buffers duplex input until the final text frame.
    """
    from xfyun_tts import stream_pcm_chunks

    segments = asyncio.Queue(maxsize=8)
    async def produce():
        buffer = ''
        async with aclosing(text_source):
            try:
                async for delta in text_source:
                    for char in delta:
                        buffer += char
                        if char in '。！？!?；;\n' or len(buffer) >= 80:
                            if buffer.strip():
                                await segments.put(buffer)
                            buffer = ''
                if buffer.strip():
                    await segments.put(buffer)
            except Exception as exc:
                await segments.put(exc)
        await segments.put(None)

    producer = asyncio.create_task(produce())
    try:
        while True:
            text = await segments.get()
            if text is None:
                return
            if isinstance(text, Exception):
                raise text
            async with aclosing(stream_pcm_chunks(cfg, text, timeout=timeout)) as audio:
                got_audio = False
                async for pcm in audio:
                    got_audio = True
                    yield pcm
                if not got_audio:
                    raise RuntimeError('TTS returned no audio for a sentence.')
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
