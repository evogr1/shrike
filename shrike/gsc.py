"""Search Console pulls (design item 14 and C4)."""

import datetime as dt
import json
import random
import time
from zoneinfo import ZoneInfo

from .errors import AuthError, QuotaError, UpstreamError

PACIFIC = ZoneInfo("America/Los_Angeles")
ROW_LIMIT = 25000
TRUNCATION_ROWS = 50000          # documented per-day, per-search-type cap
RETENTION_DAYS = 482             # ~16 months (486 d) minus a 4-day margin
RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded"}
BACKOFF = (2, 4, 8, 16, 32)
DIMS = {"site": [], "page": ["page"], "page_query": ["page", "query"]}

_sleep = time.sleep  # patched in tests


def today_pacific():
    return dt.datetime.now(PACIFIC).date()


def _status_and_reason(exc):
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None) or getattr(exc, "status_code", None)
    reason = ""
    content = getattr(exc, "content", b"") or b""
    try:
        body = json.loads(content.decode() if isinstance(content, bytes) else content)
        errs = body.get("error", {}).get("errors") or []
        if errs:
            reason = errs[0].get("reason", "")
        if not reason:
            st = body.get("error", {}).get("status", "")
            if st == "RESOURCE_EXHAUSTED":
                reason = "rateLimitExceeded"
    except Exception:
        pass
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    return status, reason


def classify(exc, auth_fix):
    """Return ('retry'|'auth'|'other', SkError) for an API exception."""
    status, reason = _status_and_reason(exc)
    if status == 429 or (status == 403 and reason in RATE_REASONS) or (status is not None and status >= 500):
        return "retry", QuotaError(f"Search Console rate limit or server error (HTTP {status} {reason})".strip(),
                                   "wait; it retries automatically on the next run")
    if status in (401, 403):
        return "auth", AuthError(f"Search Console refused access (HTTP {status} {reason})".strip(), auth_fix)
    return "other", UpstreamError(f"Search Console error: {exc!r}"[:500], "check the journal for details")


def _execute(client, prop, body, auth_fix):
    last = None
    for attempt in range(len(BACKOFF) + 1):
        try:
            return client.searchanalytics().query(siteUrl=prop, body=body).execute()
        except Exception as exc:  # googleapiclient HttpError or transport error
            kind, err = classify(exc, auth_fix)
            if kind != "retry":
                raise err from exc
            last = err
            if attempt < len(BACKOFF):
                _sleep(BACKOFF[attempt] + random.random())
    raise last


def fetch_day(client, prop, date, dims, data_state="final", pause=0.0, auth_fix=""):
    """Pull one day for one dimension set. Returns (rows, truncated)."""
    dimensions = DIMS[dims]
    rows, start = [], 0
    while True:
        body = {
            "startDate": date, "endDate": date, "dimensions": dimensions, "type": "web",
            "dataState": data_state, "rowLimit": ROW_LIMIT, "startRow": start,
        }
        resp = _execute(client, prop, body, auth_fix)
        if pause:
            _sleep(pause)
        page = resp.get("rows", []) or []
        for r in page:
            keys = r.get("keys", [])
            row = {"clicks": int(r.get("clicks", 0)), "impressions": int(r.get("impressions", 0)),
                   "ctr": float(r.get("ctr", 0.0)), "position": float(r.get("position", 0.0))}
            if dims in ("page", "page_query"):
                row["page"] = keys[0]
            if dims == "page_query":
                row["query"] = keys[1]
            rows.append(row)
        if len(page) < ROW_LIMIT or not dimensions:
            break
        start += ROW_LIMIT
    truncated = dims != "site" and len(rows) >= TRUNCATION_ROWS
    return rows, truncated


def probe(client, prop, today=None, days=14, auth_fix=""):
    """One dataState=all query grouped by date.

    Returns (first_incomplete_date, {date: impressions}) for the recent window.
    """
    today = today or today_pacific()
    body = {"startDate": (today - dt.timedelta(days=days)).isoformat(), "endDate": today.isoformat(),
            "dimensions": ["date"], "type": "web", "dataState": "all", "rowLimit": 100}
    resp = _execute(client, prop, body, auth_fix)
    fid = (resp.get("metadata") or {}).get("firstIncompleteDate")
    first_incomplete = dt.date.fromisoformat(fid) if fid else today - dt.timedelta(days=3)
    impressions = {r["keys"][0]: int(r.get("impressions", 0)) for r in resp.get("rows", []) or []}
    return first_incomplete, impressions


def available_range(first_incomplete):
    newest_final = first_incomplete - dt.timedelta(days=1)
    oldest = newest_final - dt.timedelta(days=RETENTION_DAYS)
    return oldest, newest_final


def oldest_for(last_final_date):
    """Today's oldest pullable date, derived without an API call (design C11)."""
    return (dt.date.fromisoformat(last_final_date) - dt.timedelta(days=RETENTION_DAYS)).isoformat()
