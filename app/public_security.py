"""Bounded request handling for the anonymous, sample-only Vercel demo.

The memory counters are an extra per-instance safeguard, not a distributed WAF.
No IP addresses, question text, or authentication values are logged here.
"""

import asyncio
import hashlib
import time
from collections import defaultdict
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
HEADERS = {
    "Content-Security-Policy": POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
    "Cache-Control": "no-store",
}


class PublicDemoSecurity:
    def __init__(self, app, *, body_limit=4096, per_client=40, total_limit=400,
                 window_seconds=60, clock=time.monotonic, trust_vercel_proxy=False):
        self.app = app
        self.body_limit = body_limit
        self.per_client = per_client
        self.total_limit = total_limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.trust_vercel_proxy = trust_vercel_proxy
        self.window = -1
        self.counts = defaultdict(int)
        self.total = 0

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        headers = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope['headers']}

        async def safe_send(message):
            if message['type'] == 'http.response.start':
                existing = [(k, v) for k, v in message.get('headers', []) if k.decode('latin-1').lower() not in {name.lower() for name in HEADERS}]
                message = {**message, 'headers': existing + [(key.lower().encode(), value.encode()) for key, value in HEADERS.items()]}
            await send(message)

        async def reject(status, detail, extra=None):
            response = JSONResponse({'detail': detail}, status_code=status, headers=extra)
            await response(scope, receive, safe_send)

        if scope['path'] == '/query' and scope['method'] == 'POST':
            origin = headers.get('origin')
            if origin:
                try:
                    parsed = urlsplit(origin)
                    allowed = parsed.scheme in {'http', 'https'} and parsed.netloc == headers.get('host') and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment
                except ValueError:
                    allowed = False
                if not allowed:
                    await reject(403, 'Cross-origin browser requests are not allowed')
                    return
            if headers.get('sec-fetch-site') == 'cross-site':
                await reject(403, 'Cross-site browser requests are not allowed')
                return
            if headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                await reject(415, 'Send an application/json question')
                return
            try:
                declared = int(headers.get('content-length', '0'))
                if declared < 0:
                    raise ValueError()
            except ValueError:
                await reject(400, 'Invalid request length')
                return
            if declared > self.body_limit:
                await reject(413, 'Question request exceeds 4 KB')
                return

            window = int(self.clock() // self.window_seconds)
            if window != self.window:
                self.window, self.total = window, 0
                self.counts.clear()
            address = (scope.get('client') or ('unknown', 0))[0]
            if self.trust_vercel_proxy:
                address = headers.get('x-vercel-forwarded-for', address).split(',')[0].strip()
            key = hashlib.sha256(address.encode()).digest()
            if self.total >= self.total_limit or self.counts.get(key, 0) >= self.per_client:
                await reject(429, 'Too many questions. Please wait a minute and try again.', {'Retry-After': str(self.window_seconds)})
                return
            self.total += 1
            self.counts[key] += 1

            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        body.extend(message.get('body', b''))
                        if len(body) > self.body_limit:
                            await reject(413, 'Question request exceeds 4 KB')
                            return
                        if not message.get('more_body', False):
                            break
            except TimeoutError:
                await reject(408, 'Question request timed out')
                return
            consumed = False

            async def buffered_receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()

            await self.app(scope, buffered_receive, safe_send)
            return
        await self.app(scope, receive, safe_send)
