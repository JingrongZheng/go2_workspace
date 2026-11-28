"""The robot owns accepted jobs even after the submitting client disconnects."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from onboard_dialogue import OnboardDialogue, make_app


class OnboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / 'dialogue.env'
        self.env.write_text('LLM_BASE_URL=http://unused\nLLM_MODEL=kimi-k3.1-pro-highspeed\nLLM_API_KEY=fake\nLLM_REASONING_EFFORT=low\n')
        args = SimpleNamespace(llm_env=self.env, no_audio=True, history_turns=2, tts_mode='sentences')
        self.service = OnboardDialogue(args)
        self.runner = web.AppRunner(make_app(self.service))
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.base = 'http://127.0.0.1:%s' % site._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        await self.runner.cleanup()
        self.tmp.cleanup()

    async def test_job_survives_submitter_disconnect_and_remembers_history(self):
        release = asyncio.Event()
        contexts = []
        async def reply(client, base, key, model, messages, **kwargs):
            contexts.append(messages)
            state = kwargs['assistant_state']
            state.update(role='assistant', content='你好。', reasoning_content='private reasoning')
            await release.wait()
            yield '你好。'
        with patch('onboard_dialogue.stream_reply', reply):
            async with aiohttp.ClientSession() as submitter:
                async with submitter.post(self.base + '/ask', json={'text': '第一问'}) as resp:
                    self.assertEqual(resp.status, 202)
                    job_id = (await resp.json())['id']
            # Submitting connection and session are gone before cloud response.
            release.set()
            await asyncio.wait_for(self.service.active, 2)
            async with aiohttp.ClientSession() as observer:
                async with observer.get(self.base + '/jobs/' + job_id) as resp:
                    job = await resp.json()
                    self.assertEqual(job['status'], 'done')
                    self.assertEqual(job['reply'], '你好。')
                    self.assertNotIn('reasoning', json.dumps(job))
                async with observer.post(self.base + '/ask', json={'text': '第二问'}) as resp:
                    self.assertEqual(resp.status, 202)
                await asyncio.wait_for(self.service.active, 2)
            self.assertEqual(contexts[1][1]['content'], '第一问')
            self.assertEqual(contexts[1][2]['reasoning_content'], 'private reasoning')

    async def test_busy_requests_do_not_overlap_or_reset(self):
        release = asyncio.Event()
        async def reply(*a, **kw):
            await release.wait()
            yield 'answer'
        with patch('onboard_dialogue.stream_reply', reply):
            async with aiohttp.ClientSession() as client:
                async with client.post(self.base + '/ask', json={'text': 'one'}) as resp:
                    self.assertEqual(resp.status, 202)
                async with client.post(self.base + '/ask', json={'text': 'two'}) as resp:
                    self.assertEqual(resp.status, 409)
                async with client.post(self.base + '/reset', json={}) as resp:
                    self.assertEqual(resp.status, 409)
            release.set()
            await asyncio.wait_for(self.service.active, 2)

    async def test_missing_credentials_does_not_claim_cloud_ready(self):
        self.env.write_text('LLM_API_KEY=\n')
        async with aiohttp.ClientSession() as client:
            async with client.get(self.base + '/health') as resp:
                data = await resp.json()
                self.assertFalse(data['config_ready'])
                self.assertFalse(data['cloud_connectivity_verified'])
            async with client.post(self.base + '/ask', json={'text': 'one'}) as resp:
                self.assertEqual(resp.status, 503)

    async def test_failed_turn_not_added_to_history(self):
        async def reply(*a, **kw):
            yield 'partial'
            raise RuntimeError('secret URL must not reach client')
        with patch('onboard_dialogue.stream_reply', reply):
            async with aiohttp.ClientSession() as client:
                async with client.post(self.base + '/ask', json={'text': 'one'}) as resp:
                    job_id = (await resp.json())['id']
                await asyncio.wait_for(self.service.active, 2)
                async with client.get(self.base + '/jobs/' + job_id) as resp:
                    data = await resp.json()
                    self.assertEqual(data['status'], 'failed')
                    self.assertNotIn('secret', json.dumps(data))
            self.assertEqual(self.service.history, [])


if __name__ == '__main__':
    unittest.main()
