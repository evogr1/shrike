"""MCP over HTTP, behind the secret path (design C9)."""

from . import __version__, routes
from .errors import SkError

VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")


def tools(remote_only):
    return [{"name": r.tool, "description": r.description, "inputSchema": routes.input_schema(r)}
            for r in routes.ROUTES if r.remote or not remote_only]


def initialize(params):
    v = params.get("protocolVersion")
    return {"protocolVersion": v if v in VERSIONS else VERSIONS[-1], "capabilities": {"tools": {}},
            "serverInfo": {"name": "shrike", "version": __version__}}


def _error(i, code, message):
    return {"jsonrpc": "2.0", "id": i, "error": {"code": code, "message": message}}


def handle(ctx, msg, remote_only=True, runner=None):
    """One JSON-RPC message in, a reply or None (notification) out."""
    if not isinstance(msg, dict) or not isinstance(msg.get("method"), str):
        return _error(None, -32600, "invalid request")
    i, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if i is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": i, "result": result}

    if method == "initialize":
        return ok(initialize(params))
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tools(remote_only)})
    if method != "tools/call":
        return _error(i, -32601, "unknown method")
    route = next((r for r in routes.ROUTES if r.tool == params.get("name") and (r.remote or not remote_only)), None)
    args = params.get("arguments") or {}
    if route is None or not isinstance(args, dict):
        return _error(i, -32602, "unknown tool or bad arguments")
    try:
        text, bad = (runner or _local)(ctx, route, args)
    except routes.BadRequest as e:
        return _error(i, -32602, str(e))
    except SkError as e:
        text, bad = routes.clip({"error": str(e), "fix_step": e.fix_step}), True
    except Exception as e:  # never leak details
        print(f"mcp tool {route.tool} failed: {e!r}")
        text, bad = "internal error", True
    return ok({"content": [{"type": "text", "text": text}], "isError": bad})


def _local(ctx, route, args):
    return routes.clip(routes.call(ctx, route, args)), False
