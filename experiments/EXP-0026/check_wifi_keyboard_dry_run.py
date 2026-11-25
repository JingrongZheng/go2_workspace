"""Clock, stale-request, watchdog and EOF tests with DDS publishing disabled."""
import json,sys,subprocess,time,struct,select
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'shared'))
from go2_wifi_keyboard import remote_command,measure_pc_minus_dock
cmd=['ssh','-T','-S',str(Path.cwd()/'.work/ssh-control/go2-wifi-new.sock'),'-o','BatchMode=yes','unitree@192.168.110.87','bash -c '+__import__('shlex').quote(remote_command(dry=True))]
p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
offset=measure_pc_minus_dock(p);p.stdin.write(b'S'+struct.pack('!q',offset));status=json.loads(p.stdout.readline());assert status['ready'] and status['dry_run']
def send(api,param='',age=0):p.stdin.write((json.dumps({'api_id':api,'parameter':param,'sent_pc_ns':time.time_ns()-int(age*1e9)})+'\n').encode())
velocity=json.dumps({'x':.35,'y':0.,'z':0.})
send(1008,velocity,age=1.);time.sleep(.15)
send(1008,velocity);time.sleep(1.)
send(1002);send(1008,velocity);time.sleep(.1);p.stdin.close();p.wait(timeout=4)
events=[json.loads(x) for x in p.stderr.read().decode().splitlines() if x.startswith('{')]
assert [e['preview_api'] for e in events]==[1008,1003,1002,1008,1003],events
assert events[1]['reason']=='watchdog' and events[-1]['reason']=='disconnect',events
out={'dry_run':True,'real_commands_sent':0,'expired_request_discarded':True,'watchdog_stop_preview':True,'disconnect_stop_preview':True,'events':events}
Path('experiments/EXP-0026/keyboard-dry-run-check.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
