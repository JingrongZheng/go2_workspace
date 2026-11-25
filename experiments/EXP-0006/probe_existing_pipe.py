"""Test one benign output envelope on the existing webrtcres pipe; no control requests."""
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
from std_msgs.msg import String
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'shared'))
from go2_webrtc_state import UnitreeWebRTCConnection,WebRTCConnectionMethod,connect_peer

async def main():
    node=rclpy.create_node('go2_existing_output_pipe_probe')
    conn=UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA,ip='192.168.123.161')
    nonce=uuid.uuid4().hex
    marker_topic='rt/go2_probe/pass_'+nonce
    pub=node.create_publisher(String,'/webrtcres',10)
    counts={'state':0,'local_marker':0,'rtc_marker':0}
    sub=node.create_subscription(String,'/webrtcres',
        lambda m:counts.__setitem__('local_marker',counts['local_marker']+int(nonce in m.data)),10)
    async def spin(seconds):
        start=time.monotonic()
        while time.monotonic()-start<seconds:
            rclpy.spin_once(node,timeout_sec=0)
            await asyncio.sleep(.01)
    try:
        await connect_peer(conn,SimpleNamespace(remote=False,ip='192.168.123.161',local_ip=None))
        @conn.datachannel.channel.on('message')
        def inspect_raw(message):
            if (isinstance(message,str) and nonce in message) or (isinstance(message,bytes) and nonce.encode() in message):
                counts['rtc_marker']+=1
                print('RTC_MARKER '+(message if isinstance(message,str) else repr(message[:300])),flush=True)
        conn.datachannel.pub_sub.subscribe('rt/lf/sportmodestate',lambda e:counts.__setitem__('state',counts['state']+1))
        conn.datachannel.pub_sub.subscribe(marker_topic,lambda e:None)
        await spin(2)
        print('READERS '+json.dumps([{'node':e.node_name,'type':e.topic_type} for e in node.get_subscriptions_info_by_topic('/webrtcres')]),flush=True)
        for i in range(3):
            payload={'type':'msg','topic':marker_topic,'data':{'marker':nonce,'sequence':i}}
            pub.publish(String(data=json.dumps(payload)))
            await spin(1)
        await spin(2)
        print('RESULT '+json.dumps(counts),flush=True)
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
