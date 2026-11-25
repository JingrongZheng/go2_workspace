"""Run the existing PC keyboard through the dock's current WiFi SSH route."""
import argparse,ipaddress,json,os,select,shlex,struct,subprocess,sys,termios,time,tty
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'shared/dddmr/real'))
from relay_sensors import measure_pc_minus_dock
sys.path.insert(0,str(ROOT/'shared'))
from go2_keyboard_control import drive,DEFAULT_LINEAR_SPEED

def remote_command(check=False,dry=False):
    xml='<CycloneDDS><Domain><General><NetworkInterfaceAddress>eth10</NetworkInterfaceAddress></General></Domain></CycloneDDS>'
    setup='set -e\nsource /opt/ros/foxy/setup.bash >&2\nsource ~/cyclonedds_ws/install/local_setup.bash >&2\nsource ~/go2-keyboard-control/ws/install/local_setup.bash >&2\n'
    setup+='export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp PYTHONNOUSERSITE=1\n'
    setup+='export CYCLONEDDS_URI='+shlex.quote(xml)+'\nexec /usr/bin/python3 ~/go2-keyboard-control/go2_wifi_control_source.py'
    return setup+(' --check' if check else '')+(' --dry-run' if dry else '')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--host',type=ipaddress.IPv4Address,default='192.168.110.87');p.add_argument('--socket',type=Path,default=ROOT/'.work/ssh-control/go2-wifi-new.sock');p.add_argument('--check',action='store_true');p.add_argument('--robot',action='store_true');p.add_argument('--linear-speed',type=float,default=DEFAULT_LINEAR_SPEED);args=p.parse_args()
    if not 0<args.linear_speed<=DEFAULT_LINEAR_SPEED:p.error('Linear speed must be >0 and <=0.35 m/s')
    if not args.check and not sys.stdin.isatty():p.error('Use an interactive PC terminal')
    cmd=['ssh','-T','-S',str(args.socket),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=5','-o','ServerAliveInterval=1','-o','ServerAliveCountMax=2',f'unitree@{args.host}','bash -c '+shlex.quote(remote_command(args.check,not args.robot and not args.check))]
    if args.check:return subprocess.call(cmd)
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,bufsize=0)
    settings=None
    try:
        offset=measure_pc_minus_dock(proc);proc.stdin.write(b'S'+struct.pack('!q',offset));proc.stdin.flush()
        if not select.select([proc.stdout],[],[],8)[0]:raise TimeoutError('Receiver did not become ready')
        status=json.loads(proc.stdout.readline())
        if not status.get('ready'):raise RuntimeError(status.get('error','Receiver failed'))
        print('Live robot control' if args.robot else 'Preview only: no robot requests will be published')
        print('1 StandUp | 2 BalanceStand | 3 StandDown | 4 Damp')
        print('W/S forward/back 0.35 m/s | A/D turn 1 rad/s | Space stop | Q quit',flush=True)
        os.set_blocking(proc.stdin.fileno(),False)
        def send(m):
            data=(json.dumps({'api_id':m.header.identity.api_id,'parameter':m.parameter,'sent_pc_ns':time.time_ns()})+'\n').encode()
            if os.write(proc.stdin.fileno(),data)!=len(data):raise ConnectionError('Partial control write')
        fd=sys.stdin.fileno();settings=termios.tcgetattr(fd);tty.setcbreak(fd);drive(send,fd,args.linear_speed)
    except (OSError,RuntimeError,TimeoutError,ValueError) as error:print(str(error),file=sys.stderr);return 1
    except KeyboardInterrupt:pass
    finally:
        if settings is not None:termios.tcsetattr(sys.stdin.fileno(),termios.TCSADRAIN,settings)
        proc.stdin.close()
        try:proc.wait(timeout=4)
        except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=3)
    return 0
if __name__=='__main__':raise SystemExit(main())
