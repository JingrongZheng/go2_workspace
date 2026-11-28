#!/usr/bin/env python3
"""Deploy to robot's ~/go2-dialogue using an existing SSH authentication.

Uses offline ARM64 wheels and vendor copy of the already-used WebRTC driver.
Credentials are sent separately over SSH only when target files do not exist.
"""
import argparse
import shlex
import subprocess
import tarfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='192.168.123.18')
    p.add_argument('--user', default='unitree')
    p.add_argument('--socket', default=str(root / '.work/ssh-control/go2.sock'))
    p.add_argument('--code-only', action='store_true', help='Update code on an existing runtime')
    args = p.parse_args()
    stage = root / '.work/onboard-dialogue'
    stage.mkdir(parents=True, exist_ok=True)
    archive = stage / 'code.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for path in (root / 'shared/audio').rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                tar.add(path, arcname=str(path.relative_to(root)))
        vendor = root / '.work/webrtc-venv/lib/python3.10/site-packages/unitree_webrtc_connect'
        for path in vendor.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                tar.add(path, arcname='vendor/unitree_webrtc_connect/' + str(path.relative_to(vendor)))
        for path in vendor.parent.glob('unitree_webrtc_connect-*.dist-info/licenses/*'):
            if path.is_file():
                tar.add(path, arcname='vendor/licenses/' + path.name)
        if not args.code_only:
            wheels = sorted((stage / 'wheels').glob('*.whl'))
            if not wheels:
                raise RuntimeError('Download offline ARM64 wheels first.')
            for path in wheels:
                tar.add(path, arcname='wheels/' + path.name)
            tar.add(stage / 'libportaudio2_arm64.deb', arcname='libportaudio2_arm64.deb')
    ssh = ['ssh', '-S', args.socket, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', args.user + '@' + args.host]
    with archive.open('rb') as data:
        subprocess.run(ssh + ['umask 077; mkdir -p ~/go2-dialogue; tar -xz -C ~/go2-dialogue'], stdin=data, check=True)
    # Remove only retired files from older deployments; preserve config/data.
    cleanup = """from pathlib import Path
root = Path.home() / 'go2-dialogue/shared/audio'
retired = ['go2_audio_play.py', 'xfyun_clone_train.py', 'run_audio_play.sh', 'run_clone_train.sh', 'compare_audio_paths.py']
for name in retired:
    path = root / name
    if path.is_file():
        path.unlink()
    if path.suffix == '.py':
        for cache in (root / '__pycache__').glob(path.stem + '.*.pyc'):
            cache.unlink()
print('Retired standalone audio code removed.')
"""
    subprocess.run(ssh + ['python3 -c ' + shlex.quote(cleanup)], check=True)
    # Do not overwrite a robot's existing configuration/credentials.
    for name in ['dialogue.env', 'xfyun.env', 'xfyun_voices.json']:
        source = root / '.work' / name
        if source.is_file():
            command = ('umask 077; mkdir -p ~/go2-dialogue/.work; '
                       'if test -f ~/go2-dialogue/.work/{0}; then cat >/dev/null; '
                       'else cat > ~/go2-dialogue/.work/{0}; fi').format(name)
            with source.open('rb') as data:
                subprocess.run(ssh + [command], stdin=data, check=True)
    if not args.code_only:
        subprocess.run(ssh + ['bash ~/go2-dialogue/shared/audio/install_onboard_runtime.sh'], check=True)
    print('Code deployed to robot: ~/go2-dialogue. Service/cloud validation is separate.')


if __name__ == '__main__':
    main()
