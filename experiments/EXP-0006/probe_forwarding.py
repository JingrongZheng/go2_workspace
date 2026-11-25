"""Publish isolated DDS markers and look for their return over the stock WebRTC service."""
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import rclpy
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import String
from unitree_api.msg import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from go2_webrtc_state import UnitreeWebRTCConnection, WebRTCConnectionMethod, connect_peer

async def main():
    node = rclpy.create_node('go2_isolated_forwarding_probe')
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip='192.168.123.161')
    nonce = uuid.uuid4().hex
    names = {'string': '/go2_probe/string_' + nonce, 'request': '/go2_probe/request_' + nonce}
    counts = {'state': 0, 'dds_string': 0, 'dds_request': 0, 'webrtc_marker': 0}
    pubs = {key: node.create_publisher(typ, names[key], 10)
            for key, typ in [('string', String), ('request', Request)]}
    def received(key):
        def callback(msg):
            if nonce in (msg.data if key == 'string' else msg.parameter):
                counts['dds_' + key] += 1
        return callback
    subs = [node.create_subscription(typ, names[key], received(key), 10)
            for key, typ in [('string', String), ('request', Request)]]
    def rtc_marker(envelope):
        if nonce in json.dumps(envelope):
            counts['webrtc_marker'] += 1
            print('FORWARDED ' + json.dumps(envelope), flush=True)
    def state(envelope):
        counts['state'] += 1
    try:
        await connect_peer(conn, SimpleNamespace(remote=False, ip='192.168.123.161', local_ip=None))
        conn.datachannel.pub_sub.subscribe('rt/lf/sportmodestate', state)
        # Try canonical DDS spelling, ROS spelling and unprefixed spelling.
        for key in names:
            for spelling in ('rt' + names[key], names[key], names[key].lstrip('/')):
                conn.datachannel.pub_sub.subscribe(spelling, rtc_marker)
        print('TEST_TOPICS ' + json.dumps(names), flush=True)
        started, next_pub = time.monotonic(), 0
        while time.monotonic() - started < 15:
            rclpy.spin_once(node, timeout_sec=0)
            now = time.monotonic()
            if now >= next_pub:
                pubs['string'].publish(String(data=nonce))
                msg = Request()
                msg.parameter = nonce
                pubs['request'].publish(msg)
                next_pub = now + 0.1
            await asyncio.sleep(0.01)
        endpoints = {}
        for key, topic in names.items():
            endpoints[key] = [{'node': e.node_name, 'namespace': e.node_namespace,
                               'type': e.topic_type, 'gid': list(e.endpoint_gid)}
                              for e in node.get_subscriptions_info_by_topic(topic)]
        print('DDS_SUBSCRIBERS ' + json.dumps(endpoints), flush=True)
        print('COUNTS ' + json.dumps(counts), flush=True)
        if counts['state'] == 0:
            raise RuntimeError('No stock telemetry: forwarding result is inconclusive.')
        if not counts['dds_string'] or not counts['dds_request']:
            raise RuntimeError('No local DDS markers: forwarding result is inconclusive.')
    finally:
        await conn.disconnect()
        node.destroy_node()

os.environ['NO_PROXY'] = '192.168.123.161,localhost,127.0.0.1'
os.environ['no_proxy'] = os.environ['NO_PROXY']
rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
try:
    asyncio.run(main())
finally:
    rclpy.try_shutdown()
