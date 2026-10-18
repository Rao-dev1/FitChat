"""Vercel entry point: Vercel looks for an ASGI app called `app` in this file.

vercel.json sends every URL to this function and passes the real path along in
the `__p` query value, because some Vercel setups hand the function the rewrite
target ("/api/index") instead of the address that was typed. We put the real
path back before FastAPI sees the request.
"""
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app as _fastapi  # noqa: E402


class RestorePath:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            pairs = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
            real = next((v for k, v in pairs if k == "__p"), None)
            if real is not None:
                rest = [(k, v) for k, v in pairs if k != "__p"]
                path = "/" + real.lstrip("/")
                scope = dict(scope, path=path, raw_path=path.encode(),
                             query_string=urlencode(rest).encode())
        await self.inner(scope, receive, send)


app = RestorePath(_fastapi)
