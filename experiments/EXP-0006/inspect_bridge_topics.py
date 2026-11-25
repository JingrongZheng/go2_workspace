"""Observe existing DDS bridge topic envelopes; do not publish on them."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import rclpy
from rclpy.signals import SignalHandlerOptions
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from go2_webrtc_state import UnitreeWebRTCConnection, WebRTCConnectionMethod, connect_peer

TOPICS = ['/webrtcreq', '/webrtcres', '/xfk_webrtcreq', '/xfk_webrtcres']

def shape(value, level=0):
    if level > 3:
        return type(value).__name__
    if isinstance(value, dict):
        return {key: shape(val, level+1) for key,val in value.items()}
    if isinstance(value, list):
        return ['length=' + str(len(value))] + ([shape(value[0], level+1)] if value else [])
    return type(value).__name__

async def main():
    node=rclpy.create_node('go2_bridge_envelope_observer')
    conn=UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip='192.168.123.161')
    counts={t:0 for t in TOPICS}
    samples={t:[] for t in TOPICS}
    subscriptions=[]
    def callback(topic):
        def receive(msg):
            counts[topic]+=1
            if len(samples[topic]) >= 5:
                return
            try:
                data=json.loads(msg.data)
                entry={'length':len(msg.data), 'shape':shape(data)}
                if isinstance(data,dict):
                    entry['type']=data.get('type')
                    entry['topic']=data.get('topic')
                    for field in ('data','info'):
                        if isinstance(data.get(field),dict):
                            entry[field+'_req_type']=data[field].get('req_type')
                samples[topic].append(entry)
            except (ValueError,TypeError):
                samples[topic].append({'length':len(msg.data),'format':'not JSON'})
        return receive
    for topic in TOPICS:
        subscriptions.append(node.create_subscription(String, topic, callback(topic), qos_profile_sensor_data))
    async def spin(seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            rclpy.spin_once(node,timeout_sec=0)
            await asyncio.sleep(.01)
    try:
        await spin(2)
        for topic in TOPICS:
            print('ENDPOINTS ' + json.dumps({'topic':topic,
                'publishers':[{'node':e.node_name,'type':e.topic_type} for e in node.get_publishers_info_by_topic(topic)],
                'subscribers':[{'node':e.node_name,'type':e.topic_type} for e in node.get_subscriptions_info_by_topic(topic)]}),flush=True)
        await connect_peer(conn,SimpleNamespace(remote=False,ip='192.168.123.161',local_ip=None))
        states=[0]
        conn.datachannel.pub_sub.subscribe('rt/lf/sportmodestate',lambda e:states.__setitem__(0,states[0]+1))
        # A marker on a unique non-control topic lets us recognize generic request forwarding.
        conn.datachannel.pub_sub.publish_without_callback('rt/go2_probe/observe_only',{'marker':'go2_envelope_probe'})
        await spin(8)
        print('RESULT '+json.dumps({'state':states[0],'counts':counts,'samples':samples}),flush=True)
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
