#!/usr/bin/env python3
"""One bounded ARP sweep of the robot subnet plus Hesai's documented example IP."""
import ipaddress
import select
import socket
import struct
import time

interface = 'eth10'
source_ip = '192.168.123.18'
with open('/sys/class/net/eth10/address') as stream:
    source_mac = bytes.fromhex(stream.read().strip().replace(':', ''))
targets = [str(ip) for ip in ipaddress.ip_network('192.168.123.0/24').hosts()
           if str(ip) != source_ip]
targets.append('192.168.1.201')
seen = set()
with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0806)) as receiver:
    receiver.bind((interface, 0))
    def drain(wait):
        if not select.select([receiver], [], [], wait)[0]:
            return
        data = receiver.recv(65535)
        if len(data) < 42 or data[12:14] != b'\x08\x06' or data[20:22] != b'\x00\x02':
            return
        pair = (socket.inet_ntoa(data[28:32]), ':'.join(f'{v:02x}' for v in data[22:28]))
        if pair not in seen:
            seen.add(pair)
            print('ARP_REPLY', *pair, flush=True)
    print('ARP_PROBE_START: 192.168.123.0/24 and 192.168.1.201; no IP configuration changes', flush=True)
    for target in targets:
        request = (b'\xff'*6 + source_mac + b'\x08\x06' +
                   struct.pack('!HHBBH', 1, 0x0800, 6, 4, 1) + source_mac +
                   socket.inet_aton(source_ip) + b'\x00'*6 + socket.inet_aton(target))
        receiver.send(request)
        drain(0.04)
    end = time.monotonic()+3
    while time.monotonic() < end:
        drain(min(0.2, max(0, end-time.monotonic())))
print('ARP_PROBE_DONE', len(seen), 'responding addresses', flush=True)
