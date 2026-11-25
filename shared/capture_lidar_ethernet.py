#!/usr/bin/env python3
"""Bounded Linux Ethernet metadata capture for a sensor link; no payload storage."""
import collections
import json
import select
import socket
import struct
import sys
import time


def describe(data):
    if len(data) < 14:
        return None
    mac = ':'.join(f'{b:02x}' for b in data[6:12])
    kind = struct.unpack_from('!H', data, 12)[0]
    offset = 14
    if kind == 0x8100 and len(data) >= 18:
        kind = struct.unpack_from('!H', data, 16)[0]
        offset = 18
    payload = data[offset:]
    if kind == 0x0806 and len(payload) >= 28:
        return ('ARP', mac, struct.unpack_from('!H', payload, 6)[0],
                socket.inet_ntoa(payload[14:18]), socket.inet_ntoa(payload[24:28]))
    if kind == 0x0800 and len(payload) >= 28 and payload[9] == 17:
        header = (payload[0] & 15) * 4
        if header < 20 or len(payload) < header + 8:
            return None
        source, target = socket.inet_ntoa(payload[12:16]), socket.inet_ntoa(payload[16:20])
        if source == '192.168.123.161':
            return None  # Known high-rate robot stream, already identified in EXP-0004.
        src_port, dst_port, length = struct.unpack_from('!HHH', payload, header)
        return ('UDP', mac, source, src_port, target, dst_port, length)
    return None


def main():
    interface = sys.argv[1] if len(sys.argv) > 1 else 'eth10'
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 25
    if not 0 < seconds <= 60:
        raise SystemExit('Duration must be in (0,60].')
    counts = collections.Counter()
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)) as receiver:
        receiver.bind((interface, 0))
        # Socket-scoped promiscuous membership is removed automatically on close.
        membership = struct.pack('IHH8s', socket.if_nametoindex(interface), 1, 0, b'')
        receiver.setsockopt(263, 1, membership)  # SOL_PACKET, PACKET_ADD_MEMBERSHIP
        print(f'CAPTURE START interface={interface} seconds={seconds}; ARP/UDP metadata only', flush=True)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ready, _, _ = select.select([receiver], [], [], max(0, min(1, end-time.monotonic())))
            if not ready:
                continue
            description = describe(receiver.recv(65535))
            if description is not None:
                counts[description] += 1
                if counts[description] == 1:
                    print('FIRST ' + json.dumps(description), flush=True)
    for description, count in counts.items():
        print('COUNT ' + json.dumps([count, *description]), flush=True)
    print('CAPTURE DONE', flush=True)


if __name__ == '__main__':
    main()
