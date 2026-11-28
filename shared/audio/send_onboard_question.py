#!/usr/bin/env python3
"""PC submits only text over SSH. LLM/TTS and audio all run on the robot."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('text', nargs='?')
    p.add_argument('--host', default='192.168.123.18')
    p.add_argument('--user', default='unitree')
    p.add_argument('--socket', help='Override SSH control socket; known wired/Wi-Fi hosts are selected automatically.')
    p.add_argument('--health', action='store_true')
    p.add_argument('--reset', action='store_true')
    p.add_argument('--submit-only', action='store_true')
    args = p.parse_args()
    if not (args.text or args.health or args.reset):
        p.error('Provide text, --health or --reset')
    if args.socket is None:
        control_dir = Path(__file__).resolve().parents[2] / '.work/ssh-control'
        if args.host == os.environ.get('GO2_WIRED_HOST', '192.168.123.18'):
            args.socket = str(control_dir / 'go2.sock')
        elif args.host == os.environ.get('GO2_WIFI_HOST', '192.168.110.87'):
            args.socket = str(control_dir / 'go2-wifi.sock')
        else:
            # Never reuse a different host's connection: OpenSSH multiplexing
            # routes via the socket even when the requested hostname differs.
            args.socket = 'none'
    remote = ['python3', 'go2-dialogue/shared/audio/onboard_request.py']
    for flag in ('health', 'reset', 'submit_only'):
        if getattr(args, flag):
            remote.append('--' + flag.replace('_', '-'))
    payload = json.dumps({'text': args.text}, ensure_ascii=False) if args.text else ''
    # Arguments and stdin are separate; questions are never interpolated in a shell.
    return subprocess.run(['ssh', '-S', args.socket, '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=5', args.user + '@' + args.host] + remote,
        input=payload, encoding='utf-8').returncode


if __name__ == '__main__':
    sys.exit(main())
