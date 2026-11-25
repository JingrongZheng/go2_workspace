"""Check a private Request/Response service through the original WebRTC bridge."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid
from types import SimpleNamespace

import rclpy
from rclpy.signals import SignalHandlerOptions
from unitree_api.msg import Request, Response
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'shared'))
from go2_webrtc_state import UnitreeWebRTCConnection,WebRTCConnectionMethod,connect_peer,DATA_CHANNEL_TYPE

async def main():
    node=rclpy.create_node('go2_private_api_probe')
    nonce=uuid.uuid4().hex
    topic='/api/go2_probe_'+nonce
    counts={'state':0,'dds_request':0,'dds_response':0,'webrtc_response':0,'webrtc_marker':0}
    pub=node.create_publisher(Response,topic+'/response',10)
    # Own-origin field lets the callback distinguish the local baseline request.
    def serve(request):
        counts['dds_request']+=1
        if request.parameter != nonce:
            return
        reply=Response()
        reply.header.identity.id=request.header.identity.id
        reply.header.identity.api_id=request.header.identity.api_id
        reply.header.status.code=0
        reply.data=json.dumps({'marker':nonce,'source':'private_dds_echo'})
        pub.publish(reply)
    server=node.create_subscription(Request,topic+'/request',serve,10)
    check=node.create_subscription(Response,topic+'/response',lambda m:counts.__setitem__('dds_response',counts['dds_response']+1),10)
    req_pub=node.create_publisher(Request,topic+'/request',10)
    conn=UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA,ip='192.168.123.161')
    def received(envelope):
        counts['webrtc_response']+=1
        if nonce in json.dumps(envelope):
            counts['webrtc_marker']+=1
            print('MARKER '+json.dumps(envelope),flush=True)
    async def spin(seconds):
        start=time.monotonic()
        while time.monotonic()-start<seconds:
            rclpy.spin_once(node,timeout_sec=0)
            await asyncio.sleep(.01)
    try:
        await connect_peer(conn,SimpleNamespace(remote=False,ip='192.168.123.161',local_ip=None))
        conn.datachannel.pub_sub.subscribe('rt/lf/sportmodestate',lambda e:counts.__setitem__('state',counts['state']+1))
        conn.datachannel.pub_sub.subscribe('rt'+topic+'/response',received)
        await spin(2)
        before=counts['dds_request']
        for i in range(3):
            conn.datachannel.pub_sub.publish_without_callback('rt'+topic+'/request',
                {'header':{'identity':{'id':100+i,'api_id':9001}},'parameter':nonce},DATA_CHANNEL_TYPE['REQUEST'])
            await spin(1)
        remote_requests=counts['dds_request']-before
        # Verify server and DDS paths separately; these may also trigger RTC responses.
        baseline_before=counts['webrtc_marker']
        for i in range(3):
            msg=Request()
            msg.header.identity.id=200+i
            msg.header.identity.api_id=9001
            msg.parameter=nonce
            req_pub.publish(msg)
            await spin(1)
        await spin(2)
        print('RESULT '+json.dumps({'topics':topic,'counts':counts,'requests_from_webrtc':remote_requests,
            'webrtc_markers_after_local_baseline':counts['webrtc_marker']-baseline_before,
            'response_subscribers':[{'node':e.node_name,'type':e.topic_type} for e in node.get_subscriptions_info_by_topic(topic+'/response')]}),flush=True)
    finally:
        await conn.disconnect()
        node.destroy_node()

os.environ['NO_PROXY']='192.168.123.161,localhost,127.0.0.1'
os.environ['no_proxy']=os.environ['NO_PROXY']
rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
try:
    asyncio.run(main())
finally:
    rclpy.try_shutdown()
