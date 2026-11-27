"""shrike-server: read-only HTTP API and remote MCP (design C8)."""

import hmac
import json
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import mcp_remote, routes
from .config import load_config, load_secrets
from .errors import ConfigError, SkError

MAX_BODY = 4 * 1024 * 1024
_MCP = re.compile(r"/mcp/[^\s/?\"']+")


def mask(text):
    return _MCP.sub("/mcp/***", text)


def make_server(ctx, host=None, port=None):
    api_key, secret = ctx.secrets.api_key.encode(), ctx.secrets.mcp_secret.encode()

    class H(BaseHTTPRequestHandler):
        server_version = "shrike"
        timeout = 60

        def log_message(self, fmt, *args):
            sys.stderr.write(mask(f"{self.address_string()} {fmt % args}") + "\n")

        def reply(self, status, body=None):
            data = b"" if body is None else json.dumps(body, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def error(self, status, msg, fix=None):
            self.reply(status, {"error": msg, "fix_step": fix})

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY or n < 0:
                self.close_connection = True
                self.error(413, "body too large")
                return None
            return self.rfile.read(n)

        def authorized(self):
            sent = self.headers.get("X-API-Key") or ""
            auth = self.headers.get("Authorization") or ""
            if not sent and auth.startswith("Bearer "):
                sent = auth[7:]
            return hmac.compare_digest(sent.encode("utf-8", "replace"), api_key)

        def handle_any(self):
            try:
                self.route()
            except SkError as e:
                self.error(e.status, str(e), e.fix_step)
            except Exception as e:  # no traceback or request data in the response or log
                sys.stderr.write(mask(f"internal error: {e!r}") + "\n")
                self.error(500, "internal error")

        do_GET = do_POST = do_PUT = do_DELETE = handle_any

        def route(self):
            u = urllib.parse.urlsplit(self.path)
            if u.path == "/health" and self.command == "GET":
                return self.reply(200, {"ok": True})
            if u.path.startswith("/mcp/"):
                given = u.path[5:].strip("/").encode("utf-8", "replace")
                if not secret or not hmac.compare_digest(given, secret):
                    return self.error(404, "not found")
                if self.command != "POST":
                    return self.error(405, "method not allowed")
                raw = self.body()
                if raw is None:
                    return
                try:
                    msg = json.loads(raw)
                except ValueError:
                    return self.error(400, "body is not JSON")
                msgs = msg if isinstance(msg, list) else [msg]
                out = [r for r in (mcp_remote.handle(ctx, m) for m in msgs) if r is not None]
                if not out:
                    return self.reply(202)
                return self.reply(200, out if isinstance(msg, list) else out[0])
            if u.path.startswith("/v1/") and not self.authorized():
                return self.error(401, "missing or wrong API key")
            matches = [r for r in routes.ROUTES if r.path == u.path]
            if not matches:
                return self.reply(404, {"error": "unknown route", "routes": [r.path for r in routes.ROUTES]})
            route = next((r for r in matches if r.method == self.command), None)
            if route is None:
                return self.error(405, "method not allowed")
            if self.command == "GET":
                args = dict(urllib.parse.parse_qsl(u.query))
            else:
                raw = self.body()
                if raw is None:
                    return
                try:
                    args = json.loads(raw or b"{}")
                    assert isinstance(args, dict)
                except (ValueError, AssertionError):
                    return self.error(400, "body is not a JSON object")
            result = routes.call(ctx, route, args)
            return self.reply(202 if route.method == "POST" else 200, result)

    return ThreadingHTTPServer((host or ctx.cfg.server_host, ctx.cfg.server_port if port is None else port), H)


def main():
    try:
        ctx = routes.ServerContext(load_config(), load_secrets("server"))
    except ConfigError as e:
        print(f"config error: {e}\nfix: {e.fix_step}", file=sys.stderr)
        return 2
    srv = make_server(ctx)
    print(f"shrike-server on {ctx.cfg.server_host}:{ctx.cfg.server_port}", file=sys.stderr)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
