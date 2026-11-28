"""Local protocol tests; no cloud calls and no robot connection."""
import asyncio
import base64
import contextlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streaming_dialogue import RobotSink, run_turn, stream_reply
from xfyun_tts import XfyunConfig
from xfyun_duplex import stream_text_pcm


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runners = []

    async def asyncTearDown(self):
        for runner in self.runners:
            await runner.cleanup()

    async def server(self, routes):
        app = web.Application()
        for method, path, handler in routes:
            app.router.add_route(method, path, handler)
        runner = web.AppRunner(app)
        await runner.setup()
        self.runners.append(runner)
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        return f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'

    def cfg(self, url):
        return XfyunConfig('test-app', 'test-key', 'test-secret', res_id='test-voice', url=url)

    async def test_audio_arrives_before_llm_finishes(self):
        heard = asyncio.Event()
        sent = []
        pcm = b'\x00\x01' * 480
        async def llm(request):
            body = await request.json()
            self.assertTrue(body['stream'])
            self.assertEqual(body['reasoning_effort'], 'low')
            resp = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
            await resp.prepare(request)
            async def event(delta, finish=None):
                raw = ('data: ' + json.dumps({'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}, ensure_ascii=False) + '\n\n').encode()
                # Fragment inside Chinese UTF-8 sequences, as real HTTP chunks can.
                for i in range(0, len(raw), 7):
                    await resp.write(raw[i:i+7])
            await event({'reasoning_content': '不能播报的思考'})
            await event({'content': '你好，'})
            await asyncio.wait_for(heard.wait(), 3)
            await event({'content': '我是 Go2。'})
            await event({}, 'stop')
            await resp.write(b'data: [DONE]\n\n')
            return resp
        async def tts(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                data = json.loads(msg.data)
                sent.append(data)
                status = data['header']['status']
                await ws.send_json({'header': {'code': 0, 'status': status}, 'payload': {'audio': {
                    'status': status, 'audio': base64.b64encode(pcm).decode() if status != 2 else ''}}})
                if status == 2:
                    break
            return ws
        base = await self.server([('POST', '/chat/completions', llm), ('GET', '/tts', tts)])
        class Sink:
            def __init__(self):
                self.data = b''
            async def write(self, chunk):
                self.data += chunk
                heard.set()
            async def finish(self):
                pass
        sink = Sink()
        cfg = self.cfg(base.replace('http:', 'ws:') + '/tts')
        async with aiohttp.ClientSession() as session:
            assistant = {}
            source = stream_reply(session, base, 'fake', 'fake', [], reasoning_effort='low', assistant_state=assistant)
            reply, metrics = await asyncio.wait_for(run_turn(source, cfg, sink, "duplex"), 5)
        self.assertEqual(reply, '你好，我是 Go2。')
        self.assertEqual(assistant['reasoning_content'], '不能播报的思考')
        self.assertEqual(assistant['content'], reply)
        self.assertLessEqual(metrics['first_audio_ms'], metrics['llm_done_ms'])
        self.assertEqual(sink.data, pcm * 2)
        self.assertEqual([r['header']['status'] for r in sent], [0, 1, 2])
        self.assertEqual([r['payload']['text']['seq'] for r in sent], [0, 1, 2])
        decoded = [base64.b64decode(r['payload']['text']['text']).decode() for r in sent]
        self.assertEqual(decoded, ['你你好，', '我是 Go2。', ''])

    async def test_sentence_audio_overlaps_text_generation(self):
        heard = asyncio.Event()
        async def source():
            yield '你好。'
            await asyncio.wait_for(heard.wait(), 1)
            yield '再见。'
        async def synthesize(cfg, text, **kwargs):
            yield text.encode()
        class Sink:
            async def write(self, chunk):
                heard.set()
            async def finish(self):
                pass
        with patch('xfyun_tts.stream_pcm_chunks', synthesize):
            reply, _ = await asyncio.wait_for(run_turn(source(), None, Sink()), 2)
        self.assertEqual(reply, '你好。再见。')

    async def test_resampler_independent_of_network_fragmentation(self):
        import numpy as np
        from webrtc_audio import StreamingPcmResampler
        raw = np.round(10000 * np.sin(2 * np.pi * 9000 * np.arange(4800) / 24000)).astype('<i2').tobytes()
        whole = StreamingPcmResampler(24000)
        expected = np.concatenate([whole.push(raw), whole.flush()])
        fragmented = StreamingPcmResampler(24000)
        actual = np.concatenate([fragmented.push(raw[i:i+137]) for i in range(0, len(raw), 137)] + [fragmented.flush()])
        self.assertEqual(len(actual), 9600)
        np.testing.assert_array_equal(actual, expected)
        power = np.abs(np.fft.rfft(actual * np.hanning(len(actual)))) ** 2
        frequency = np.fft.rfftfreq(len(actual), 1/48000)
        self.assertLess(power[frequency > 14000].sum() / power.sum(), 1e-7)

    async def test_sentence_synthesis_keeps_comma_context(self):
        from xfyun_duplex import stream_sentence_pcm
        calls = []
        async def source():
            for delta in ['你好，', '我是机器狗。', '你可以问我问题。']:
                yield delta
        async def synthesize(cfg, text, **kwargs):
            calls.append(text)
            yield b'\x00\x00'
        with patch('xfyun_tts.stream_pcm_chunks', synthesize):
            _ = [chunk async for chunk in stream_sentence_pcm(None, source())]
        self.assertEqual(calls, ['你好，我是机器狗。', '你可以问我问题。'])

    async def test_llm_disconnect_is_failure(self):
        async def handler(request):
            return web.Response(text='data: {"choices":[{"delta":{"content":"半句"}}]}\n\n', content_type='text/event-stream')
        base = await self.server([('POST', '/chat/completions', handler)])
        async with aiohttp.ClientSession() as session:
            with self.assertRaisesRegex(RuntimeError, 'before completion'):
                _ = [d async for d in stream_reply(session, base, 'fake', 'fake', [])]

    async def test_tts_error_cancels_pending_llm(self):
        closed = asyncio.Event()
        async def source():
            try:
                yield '你好'
                await asyncio.Event().wait()
            finally:
                closed.set()
        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.receive()
            await ws.send_json({'header': {'code': 123}})
            await ws.close()
            return ws
        base = await self.server([('GET', '/tts', handler)])
        with self.assertRaisesRegex(RuntimeError, '123'):
            async for _ in stream_text_pcm(self.cfg(base.replace('http:', 'ws:') + '/tts'), source()):
                pass
        await asyncio.wait_for(closed.wait(), 1)

    async def test_llm_error_cancels_pending_tts(self):
        async def source():
            yield '你好'
            raise ValueError('upstream failed')
        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for _ in ws:
                pass
            return ws
        base = await self.server([('GET', '/tts', handler)])
        with self.assertRaisesRegex(ValueError, 'upstream failed'):
            async for _ in stream_text_pcm(self.cfg(base.replace('http:', 'ws:') + '/tts'), source()):
                pass

    async def test_pcm_fragments_preserve_samples(self):
        class Track:
            def __init__(self):
                self._queue = asyncio.Queue()
                self.sizes = []
            def enqueue_pcm48k(self, pcm):
                self.sizes.append(len(pcm))
            def enqueue_silence(self, seconds):
                pass
            async def wait_drained(self):
                pass
        track = Track()
        sink = RobotSink(track, 24000)
        raw = b'\x00\x01' * 1000
        for offset in range(0, len(raw), 137):
            await sink.write(raw[offset:offset+137])
        await sink.finish()
        self.assertEqual(sum(track.sizes), 2000)
        self.assertEqual(track.sizes, [960, 960, 80])

    async def test_http_failure_does_not_expose_secret(self):
        async def handler(request):
            return web.Response(status=401, text='secret-response')
        base = await self.server([('POST', '/chat/completions', handler)])
        async with aiohttp.ClientSession() as session:
            with self.assertRaises(RuntimeError) as raised:
                _ = [d async for d in stream_reply(session, base, 'secret-key', 'fake', [])]
        self.assertNotIn('secret', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
