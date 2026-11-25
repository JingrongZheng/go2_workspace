"""Onboard high-level DDS publisher, controlled only by fresh PC key requests."""
import argparse,json,math,os,select,signal,struct,sys,time
import rclpy
from unitree_api.msg import Request
ALLOWED={1001,1002,1003,1004,1005,1008}

def validate(packet,pc_minus_dock_ns,now_ns):
    api=packet['api_id'];parameter=packet.get('parameter','')
    if api not in ALLOWED or not isinstance(parameter,str):raise ValueError('Unsupported sport request')
    age=(now_ns+pc_minus_dock_ns-int(packet['sent_pc_ns']))/1e9
    if not -.1 <= age <= .4:return None
    if api==1008:
        v=json.loads(parameter)
        if set(v)!={'x','y','z'}:raise ValueError('Unexpected velocity fields')
        x,y,z=(float(v[k]) for k in ('x','y','z'))
        if not all(map(math.isfinite,(x,y,z))) or abs(x)>.350001 or abs(y)>1e-9 or abs(z)>1.000001:raise ValueError('Velocity exceeds keyboard limits')
    elif parameter:raise ValueError('Posture/stop request must have no parameters')
    return int(api),parameter

def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--dry-run',action='store_true');args=p.parse_args()
    node=None;publisher=None;active=False
    if not args.dry_run:
        rclpy.init(args=[]);node=rclpy.create_node('go2_wifi_keyboard_receiver')
    def interrupted(signum,frame):raise KeyboardInterrupt
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
    if args.check:
        end=time.monotonic()+4;count=0
        while time.monotonic()<end:
            rclpy.spin_once(node,timeout_sec=.1);count=node.count_subscribers('/api/sport/request')
            if count:break
        from rclpy.serialization import serialize_message
        encoded=serialize_message(Request())
        types=[types for topic,types in node.get_topic_names_and_types() if topic=='/api/sport/request']
        print(json.dumps({'control_subscribers':count,'topic':'/api/sport/request','types':types,'serialized_request_bytes':len(encoded),'commands_sent':0}),flush=True)
        node.destroy_node();rclpy.shutdown();return 0 if count else 1
    sink=sys.stdout.buffer
    while True:
        b=sys.stdin.buffer.read(1)
        if b==b'T':sink.write(struct.pack('!q',time.time_ns()));sink.flush()
        elif b==b'S':break
        else:return 0
    offset_bytes=sys.stdin.buffer.read(8)
    if len(offset_bytes)!=8:return 1
    offset=struct.unpack('!q',offset_bytes)[0]
    if node is not None:
        publisher=node.create_publisher(Request,'/api/sport/request',10);deadline=time.monotonic()+5
        while publisher.get_subscription_count()==0 and time.monotonic()<deadline:rclpy.spin_once(node,timeout_sec=.1)
        if publisher.get_subscription_count()==0:
            print(json.dumps({'ready':False,'error':'No compatible robot sport subscriber'}),flush=True);node.destroy_node();rclpy.shutdown();return 1
    print(json.dumps({'ready':True,'dry_run':args.dry_run,'watchdog_s':.8}),flush=True)
    def send(api,parameter='',reason='key'):
        nonlocal active
        if args.dry_run:print(json.dumps({'preview_api':api,'parameter':parameter,'reason':reason}),file=sys.stderr,flush=True)
        else:
            m=Request();m.header.identity.api_id=api;m.parameter=parameter;publisher.publish(m)
        active=(api==1008)
    pending=bytearray();last_move=0.;fd=sys.stdin.fileno()
    try:
        while True:
            if node is not None:rclpy.spin_once(node,timeout_sec=0.)
            if select.select([fd],[],[],.04)[0]:
                chunk=os.read(fd,65536)
                if not chunk:break
                pending.extend(chunk)
                if len(pending)>16384:raise ValueError('Control input too large')
                while b'\n' in pending:
                    line,_,rest=pending.partition(b'\n');pending=bytearray(rest)
                    result=validate(json.loads(line),offset,time.time_ns())
                    if result is None:continue
                    api,parameter=result;send(api,parameter)
                    if active:last_move=time.monotonic()
            if active and time.monotonic()-last_move>.8:send(1003,reason='watchdog')
    except KeyboardInterrupt:pass
    finally:
        if active:send(1003,reason='disconnect')
        if node is not None:
            rclpy.spin_once(node,timeout_sec=.05);node.destroy_node();rclpy.try_shutdown() if hasattr(rclpy,'try_shutdown') else rclpy.shutdown()
    return 0
if __name__=='__main__':raise SystemExit(main())
