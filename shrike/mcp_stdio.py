"""shrike-mcp: stdio MCP connector that forwards to the HTTP API (design C10)."""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from . import mcp_remote, routes
from .config import load_secrets
from .errors import ConfigError


def forward(base, key, route, args):
    headers = {"X-API-Key": key}
    url, data = base.rstrip("/") + route.path, None
    clean = {k: v for k, v in args.items() if v is not None}
    if route.method == "GET":
        if clean:
            url += "?" + urllib.parse.urlencode(
                {k: ",".join(v) if isinstance(v, list) else v for k, v in clean.items()})
    else:
        data = json.dumps(clean).encode()
        headers["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=route.method)
        with urllib.request.urlopen(req, timeout=300) as r:
            text, bad = r.read().decode(), False
    except urllib.error.HTTPError as e:
        text, bad = e.read().decode(), True
    except OSError as e:
        text, bad = f"cannot reach {base}: {e}. Is the SSH tunnel open?", True
    return text[:routes.MAX_CHARS], bad


def main():
    try:
        key = load_secrets("mcp").api_key
    except ConfigError as e:
        print(f"config error: {e}\nfix: {e.fix_step}", file=sys.stderr)
        return 2
    base = os.environ.get("SHRIKE_URL", "http://127.0.0.1:8899")
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = mcp_remote.handle(None, msg, remote_only=False,
                                  runner=lambda _c, route, args: forward(base, key, route, args))
        if reply is not None:
            print(json.dumps(reply), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
