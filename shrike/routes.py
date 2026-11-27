"""One route table for the HTTP API and both MCP connectors (design C7)."""

import datetime as dt
import json
import subprocess
from dataclasses import dataclass

from . import __version__, baseline, coverage, db, fixes, opps, setup_check
from .errors import SkError

MAX_CHARS = 60000
JOBS = ("nightly", "weekly", "backfill")


class BadRequest(SkError):
    status = 400


class Conflict(SkError):
    status = 409


@dataclass(frozen=True)
class Param:
    name: str
    type: str = "str"          # str | int | bool | date | list
    required: bool = False
    default: object = None
    enum: tuple = None
    description: str = ""
    max: int = None


@dataclass
class ServerContext:
    cfg: object
    secrets: object = None


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: object
    tool: str
    description: str
    params: tuple = ()
    remote: bool = True
    needs_db: bool = True


def coerce(route, raw):
    """Check and convert raw parameters against the route's spec."""
    spec = {p.name: p for p in route.params}
    for k in raw:
        if k not in spec:
            raise BadRequest(f"unknown parameter: {k}")
    out = {}
    for p in route.params:
        v = raw.get(p.name)
        if v is None or v == "":
            if p.required:
                raise BadRequest(f"missing parameter: {p.name}")
            out[p.name] = p.default
            continue
        try:
            if p.type == "int":
                v = int(v)
                if v < 0 or (p.max and v > p.max):
                    raise ValueError
            elif p.type == "bool":
                s = str(v).lower()
                if s not in ("1", "true", "yes", "on", "0", "false", "no", "off"):
                    raise ValueError
                v = s in ("1", "true", "yes", "on")
            elif p.type == "date":
                v = dt.date.fromisoformat(str(v)).isoformat()
            elif p.type == "list":
                v = [x for x in (v if isinstance(v, list) else str(v).split(",")) if x]
                if p.enum and any(x not in p.enum for x in v):
                    raise ValueError
            else:
                v = str(v)
            if p.enum and p.type != "list" and v not in p.enum:
                raise ValueError
        except (ValueError, TypeError):
            raise BadRequest(f"bad value for parameter: {p.name}") from None
        out[p.name] = v
    return out


def setup(ctx, conn):
    return setup_check.readonly_report(ctx.cfg, ctx.cfg.data_dir)


def sites(ctx, conn):
    out = []
    for s in ctx.cfg.sites:
        first, last = db.get_range(conn, s.name)
        out.append({"name": s.name, "property": s.property, "first_date": first, "last_final_date": last,
                    "missing_days": coverage.missing_days(conn, s.name),
                    "comparison": baseline.compare(conn, s.name)})
    return {"sites": out}


def _totals(conn, view, where, args):
    r = conn.execute(f"SELECT COALESCE(SUM(clicks),0) c, COALESCE(SUM(impressions),0) i,"
                     f" SUM(position*impressions) pw FROM {view} WHERE {where}", args).fetchone()
    return {"clicks": r["c"], "impressions": r["i"], "ctr": r["c"] / r["i"] if r["i"] else 0,
            "position": r["pw"] / r["i"] if r["i"] else 0}


def performance(ctx, conn, site, page, query, start, end, compare, group_by, limit, offset):
    ctx.cfg.site(site)
    first, last = db.get_range(conn, site)
    if not last:
        raise BadRequest("no data for this site yet", "run the backfill")
    end = end or last
    start = start or max(first, (dt.date.fromisoformat(end) - dt.timedelta(days=27)).isoformat())
    if start > end or start < first:
        raise BadRequest(f"bad value for parameter: start (data runs {first} to {last})")
    if end > last:
        raise BadRequest(f"bad value for parameter: end (data runs {first} to {last})")
    if query or group_by == "query":
        view = "v_gsc_page_query"
    elif page or group_by == "page":
        view = "v_gsc_page"
    else:
        view = "v_gsc_site"
    filters = [(c, v) for c, v in (("page", page), ("query", query)) if v]

    def where(a, b):
        sql = "site = ? AND date BETWEEN ? AND ?" + "".join(f" AND {c} = ?" for c, _ in filters)
        return sql, [site, a, b, *[v for _, v in filters]]

    def shift(d, days):
        return (dt.date.fromisoformat(d) - dt.timedelta(days=days)).isoformat()

    out = {"site": site, "start": start, "end": end, "totals": _totals(conn, view, *where(start, end)), "rows": []}
    prev = None
    if compare:
        days = 364 if compare == "prev_year" else (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1
        prev = (shift(start, days), shift(end, days), days)
        out["compare_totals"] = _totals(conn, view, *where(prev[0], prev[1])) if prev[0] >= first else None
    if group_by:
        def rows(a, b, tail="", extra=()):
            sql, args = where(a, b)
            return conn.execute(
                f"SELECT {group_by} AS key, SUM(clicks) c, SUM(impressions) i, SUM(position*impressions) pw"
                f" FROM {view} WHERE {sql} GROUP BY {group_by} {tail}", [*args, *extra]).fetchall()

        def shape(r):
            return {"clicks": r["c"], "impressions": r["i"], "ctr": r["c"] / r["i"] if r["i"] else 0,
                    "position": r["pw"] / r["i"] if r["i"] else 0}

        order = "ORDER BY key" if group_by == "date" else "ORDER BY c DESC, i DESC, key"
        got = rows(start, end, order + " LIMIT ? OFFSET ?", (limit + 1, offset))
        before = {}
        if prev and out["compare_totals"] is not None:
            before = {r["key"]: shape(r) for r in rows(prev[0], prev[1])}
        for r in got[:limit]:
            item = {"key": r["key"], **shape(r)}
            if prev:
                key = shift(r["key"], prev[2]) if group_by == "date" else r["key"]
                item["compare"] = before.get(key)
            out["rows"].append(item)
        if len(got) > limit:
            out["next_offset"] = offset + limit
    return out


def opportunities(ctx, conn, site, type, status, limit):
    sql, args = [f"status IN ({','.join('?' * len(status))})"], list(status)
    for col, v in (("site", site), ("type", type)):
        if v:
            sql.append(f"{col} = ?")
            args.append(v)
    rows = conn.execute(f"SELECT * FROM opportunities WHERE {' AND '.join(sql)} ORDER BY score DESC LIMIT ?",
                        [*args, limit]).fetchall()
    return {"opportunities": [opps.load(r) for r in rows]}


def list_fixes(ctx, conn, site, measured):
    sql, args = ["1=1"], []
    if site:
        sql.append("site = ?")
        args.append(site)
    if measured is not None:
        sql.append("measured_at IS NOT NULL" if measured else "measured_at IS NULL")
    rows = conn.execute(f"SELECT * FROM fixes WHERE {' AND '.join(sql)} ORDER BY ship_date DESC", args)
    return {"fixes": [dict(r) for r in rows], "running_total": fixes.running_total(conn)}


def db_state(cfg):
    try:
        conn = db.connect_ro(cfg.db_path)
        try:
            v = db.schema_version(conn)
        finally:
            conn.close()
    except Exception:
        return "not initialized"
    if v == 0:
        return "not initialized"
    return "ok" if v >= db.latest_version() else "schema old"


def health(ctx, conn):
    if conn is None:
        return {"db": db_state(ctx.cfg), "version": __version__}
    jobs = [dict(r) for r in conn.execute("SELECT * FROM runs WHERE step IS NULL ORDER BY id DESC LIMIT 20")]
    for j in jobs:
        j["steps"] = [dict(r) for r in conn.execute(
            "SELECT step, status, error FROM runs WHERE parent_id = ? ORDER BY id", (j["id"],))]
    last = conn.execute("SELECT MAX(finished_at) FROM runs WHERE step='backup' AND status='ok'").fetchone()[0]
    age = None
    if last:
        t = dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
        age = round((dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600, 1)
    week = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"db": "ok", "version": __version__, "runs": jobs, "backup_age_hours": age,
            "missing_days": {s.name: coverage.missing_days(conn, s.name) for s in ctx.cfg.sites},
            "truncated_days": {s.name: len(coverage.truncated_days(conn, s.name)) for s in ctx.cfg.sites},
            "open_alerts": [dict(r) for r in conn.execute(
                "SELECT kind, subject, message, delivered, created_at FROM events WHERE created_at > ?"
                " ORDER BY id DESC", (week,))]}


def _systemctl(*args):
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=20)


def run_job(ctx, conn, job):
    for j in JOBS:
        state = _systemctl("show", "-p", "ActiveState", "--value", f"shrike-{j}.service").stdout.strip()
        if state in ("activating", "active", "deactivating"):
            raise Conflict("already running")
    r = _systemctl("start", "--no-block", f"shrike-{job}.service")
    if r.returncode != 0:
        raise SkError(f"could not start shrike-{job}", "check the polkit rule (docs/SETUP.md)")
    return {"unit": f"shrike-{job}.service"}


STATUSES = ("new", "sent", "done", "dismissed", "expired")

ROUTES = (
    Route("GET", "/v1/setup", setup, "shrike_setup", "Last setup-check report with one fix step per problem.",
          needs_db=False),
    Route("GET", "/v1/sites", sites, "shrike_sites", "Sites, data range, gaps and change against the baseline."),
    Route("GET", "/v1/performance", performance, "shrike_performance",
          "Google Search clicks, impressions, CTR and position. Dates are US Pacific.", (
              Param("site", required=True, description="site name from shrike_sites"),
              Param("page", description="exact page URL"), Param("query", description="exact query"),
              Param("start", "date", description="YYYY-MM-DD, default 28 days before end"),
              Param("end", "date", description="YYYY-MM-DD, default newest final date"),
              Param("compare", enum=("prev_period", "prev_year")),
              Param("group_by", enum=("date", "page", "query")),
              Param("limit", "int", default=50, max=1000), Param("offset", "int", default=0))),
    Route("GET", "/v1/opportunities", opportunities, "shrike_opportunities", "Ranked fix opportunities.", (
        Param("site"), Param("type", enum=opps.TYPES),
        Param("status", "list", default=["new", "sent"], enum=STATUSES),
        Param("limit", "int", default=50, max=1000))),
    Route("GET", "/v1/fixes", list_fixes, "shrike_fixes", "Shipped fixes, measured effects and running total.", (
        Param("site"), Param("measured", "bool"))),
    Route("GET", "/v1/health", health, "shrike_health", "Recent runs, gaps, backup age and alerts.",
          needs_db=False),
    Route("POST", "/v1/jobs", run_job, "shrike_run_job", "Start a job: nightly, weekly or backfill.",
          (Param("job", required=True, enum=JOBS),), remote=False, needs_db=False),
)


def call(ctx, route, raw):
    """Open a fresh read-only connection, validate, run the handler."""
    args = coerce(route, raw)
    state = db_state(ctx.cfg)
    if route.needs_db and state != "ok":
        raise SkError(f"database {state}", "run: systemctl start shrike-setup", status=503)
    conn = db.connect_ro(ctx.cfg.db_path) if state == "ok" else None
    try:
        return route.handler(ctx, conn, **args)
    finally:
        if conn is not None:
            conn.close()


def input_schema(route):
    types = {"str": "string", "int": "integer", "bool": "boolean", "date": "string", "list": "string"}
    props = {}
    for p in route.params:
        d = {"type": types[p.type]}
        if p.enum and p.type != "list":
            d["enum"] = list(p.enum)
        desc = p.description or ("comma-separated: " + ", ".join(p.enum) if p.type == "list" else "")
        if desc:
            d["description"] = desc
        props[p.name] = d
    return {"type": "object", "properties": props, "required": [p.name for p in route.params if p.required]}


def clip(obj):
    s = json.dumps(obj, default=str)
    if len(s) > MAX_CHARS:
        s = s[:MAX_CHARS] + "\n... truncated; use a smaller limit"
    return s


__all__ = ["ROUTES", "call", "input_schema", "clip", "ServerContext"]
