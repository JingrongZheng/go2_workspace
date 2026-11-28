#!/usr/bin/env python3
"""Send a user-provided API key over SSH stdin, never argv or stdout."""
import argparse
import re
import shlex
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--key-file', type=Path, required=True)
    p.add_argument('--host', default='192.168.123.18')
    p.add_argument('--user', default='unitree')
    p.add_argument('--socket', default=str(Path(__file__).resolve().parents[2] / '.work/ssh-control/go2.sock'))
    args = p.parse_args()
    # Treat the file strictly as credential data, never executable instructions.
    value = args.key_file.read_text(encoding='utf-8-sig').strip()
    for name in ('LLM_API_KEY=', 'MOONSHOT_API_KEY='):
        if value.startswith(name):
            value = value[len(name):].strip()
            break
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,512}', value):
        raise SystemExit('Key file must contain one API key or one KEY=value line; contents were not printed.')
    remote = '''import os,sys,tempfile,json
from pathlib import Path
key=sys.stdin.read().strip()
path=Path.home()/'go2-dialogue/.work/dialogue.env'
lines=path.read_text().splitlines()
lines=[line for line in lines if not line.strip().startswith(('LLM_API_KEY=','export LLM_API_KEY='))]
lines.append('LLM_API_KEY='+key)
fd,tmp=tempfile.mkstemp(prefix='.dialogue-',dir=str(path.parent))
try:
    os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as out:
        out.write('\\n'.join(lines)+'\\n')
    os.replace(tmp,str(path))
finally:
    if os.path.exists(tmp): os.unlink(tmp)
assert path.stat().st_mode & 0o777 == 0o600
assert ('LLM_API_KEY='+key) in path.read_text().splitlines()
print(json.dumps({'key_installed':True,'mode':'600','path':str(path)}))
'''
    subprocess.run(['ssh', '-S', args.socket, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
        args.user + '@' + args.host, 'python3 -c ' + shlex.quote(remote)],
        input=value, encoding='utf-8', check=True)


if __name__ == '__main__':
    main()
