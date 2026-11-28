#!/usr/bin/env python3
"""Submit/query the robot-local service; uses Python stdlib only, no API keys."""
import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen, build_opener, ProxyHandler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--health', action='store_true')
    p.add_argument('--reset', action='store_true')
    p.add_argument('--submit-only', action='store_true')
    args = p.parse_args()
    opener = build_opener(ProxyHandler({}))
    def call(path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request = Request('http://127.0.0.1:%d%s' % (args.port, path), data=data,
                          headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=10) as resp:
            return json.load(resp)
    if args.health:
        print(json.dumps(call('/health'), ensure_ascii=False))
        return 0
    if args.reset:
        print(json.dumps(call('/reset', {}), ensure_ascii=False))
        return 0
    body = json.load(sys.stdin)
    job = call('/ask', body)
    print('job=' + job['id'], flush=True)
    if args.submit_only:
        return 0
    emitted = 0
    while True:
        result = call('/jobs/' + job['id'])
        reply = result.get('reply', '')
        print(reply[emitted:], end='', flush=True)
        emitted = len(reply)
        if result['status'] in ('done', 'failed', 'cancelled'):
            print('\n' + json.dumps({k:v for k,v in result.items() if k != 'reply'}, ensure_ascii=False))
            return 0 if result['status'] == 'done' else 1
        time.sleep(.2)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (HTTPError, URLError, ValueError) as exc:
        print('Robot request failed: %s' % type(exc).__name__, file=sys.stderr)
        sys.exit(1)
