"""The frozen 'initial' baseline per site (design data model, C2)."""

import datetime as dt

from . import db

WINDOW = 28


def freeze(conn, site, label="initial"):
    """Write the baseline once, only when all 28 final days of the window exist. Returns True if written."""
    if conn.execute("SELECT 1 FROM baselines WHERE site = ? AND label = ?", (site, label)).fetchone():
        return False
    _, last = db.get_range(conn, site)
    if not last:
        return False
    end = dt.date.fromisoformat(last)
    start = end - dt.timedelta(days=WINDOW - 1)
    n = conn.execute(
        "SELECT COUNT(DISTINCT date) FROM v_coverage WHERE site = ? AND dims = 'site' AND state = 'final'"
        " AND date BETWEEN ? AND ?", (site, start.isoformat(), end.isoformat())).fetchone()[0]
    if n < WINDOW:
        return False
    r = conn.execute(
        "SELECT COALESCE(SUM(clicks),0) c, COALESCE(SUM(impressions),0) i,"
        " COALESCE(SUM(position * impressions),0) pw FROM v_gsc_site WHERE site = ? AND date BETWEEN ? AND ?",
        (site, start.isoformat(), end.isoformat())).fetchone()
    clicks, impr = r["c"], r["i"]
    conn.execute(
        "INSERT INTO baselines (site, label, start_date, end_date, clicks, impressions, ctr, position, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (site, label, start.isoformat(), end.isoformat(), clicks, impr,
         (clicks / impr) if impr else 0.0, (r["pw"] / impr) if impr else 0.0, db.utcnow()))
    return True


def compare(conn, site, label="initial"):
    b = conn.execute("SELECT * FROM baselines WHERE site = ? AND label = ?", (site, label)).fetchone()
    _, last = db.get_range(conn, site)
    if not b or not last:
        return None
    end = dt.date.fromisoformat(last)
    start = end - dt.timedelta(days=WINDOW - 1)
    r = conn.execute("SELECT COALESCE(SUM(clicks),0) c, COALESCE(SUM(impressions),0) i FROM v_gsc_site"
                     " WHERE site = ? AND date BETWEEN ? AND ?", (site, start.isoformat(), end.isoformat())).fetchone()

    def pct(now, then):
        return round((now - then) / then * 100, 1) if then else None

    return {
        "site": site,
        "baseline": {"clicks": b["clicks"], "impressions": b["impressions"], "start": b["start_date"],
                     "end": b["end_date"]},
        "current": {"clicks": r["c"], "impressions": r["i"], "start": start.isoformat(), "end": end.isoformat()},
        "clicks_pct": pct(r["c"], b["clicks"]),
        "impressions_pct": pct(r["i"], b["impressions"]),
    }
