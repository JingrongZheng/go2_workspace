import asyncio
import importlib.util
import io
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

spec = importlib.util.spec_from_file_location('bridge', Path(__file__).resolve().parents[2] / 'shared/go2_webrtc_state.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
local = m.parse_args(['--ip', '10.186.248.47'])
remote = m.parse_args(['--remote', '--sn', ' TEST-SN ', '--username', 'test@example.com', '--show-video'])
assert remote.sn == 'TEST-SN' and remote.region == 'cn' and remote.video
assert m.parse_args(['--remote', '--sn', 'SN', '--region', 'global']).region == 'global'
for argv in ([], ['--remote'], ['--remote', '--sn', 'SN', '--ip', '1.2.3.4'], ['--ip', '1.2.3.4', '--username', 'test@example.com'], ['--remote', '--sn', 'SN', '--local-ip', '1.2.3.4']):
    with patch('sys.stderr', new=io.StringIO()):
        try:
            m.parse_args(argv)
        except SystemExit as e:
            assert e.code == 2
        else:
            raise AssertionError(argv)
with patch.object(m, 'UnitreeWebRTCConnection') as factory:
    m.create_connection(local)
    factory.assert_called_once_with(m.WebRTCConnectionMethod.LocalSTA, ip=local.ip)
with patch.object(m, 'UnitreeWebRTCConnection') as factory, patch.object(m.sys.stdin, 'isatty', return_value=True), patch.object(m.getpass, 'getpass', return_value='test-password'):
    factory.return_value.token = 'fake-token'
    m.create_connection(remote)
    factory.assert_called_once_with(m.WebRTCConnectionMethod.Remote, serialNumber='TEST-SN', username='test@example.com', password='test-password', region='cn', device_type='Go2')
    factory.return_value.token = None
    try:
        m.create_connection(remote)
    except RuntimeError:
        pass
    else:
        raise AssertionError('missing token must fail')
with patch.object(m.sys.stdin, 'isatty', return_value=False):
    try:
        m.create_connection(remote)
    except ValueError:
        pass
    else:
        raise AssertionError('noninteractive password must be rejected')
async def check_connect():
    connection = Mock(connect=AsyncMock())
    with patch.object(m.socket, 'socket', side_effect=AssertionError('Remote must not select LAN route')), patch.object(m, 'patch', side_effect=AssertionError('Remote must not restrict ICE')):
        await m.connect_peer(connection, remote)
    connection.connect.assert_awaited_once()
    connection = Mock(connect=AsyncMock())
    with patch.object(m.socket, 'socket') as sock:
        sock.return_value.__enter__.return_value.getsockname.return_value = ('10.186.248.173', 1234)
        await m.connect_peer(connection, local)
    connection.connect.assert_awaited_once()
asyncio.run(check_connect())
request = m.Request()
request.header.identity.api_id = 1008
request.parameter = '{"x":0.35,"y":0,"z":1.0}'
assert m.command_payload(request)['header']['identity']['api_id'] == 1008
request.parameter = '{"x":0.36,"y":0,"z":0}'
try:
    m.command_payload(request)
except ValueError:
    pass
else:
    raise AssertionError('velocity bound lost')
print('PASS: CLI validation, LocalSTA compatibility, Remote credentials/token/ICE routing, motion bounds; no network or motion sent.')
