"""Fix tracking and measurement (design C6)."""

import datetime as dt
import re
import statistics

from . import db, gsc


def _shipped_line(desc):
    m = re.search(r"^shipped:\s*(\d{4}-\d{2}-\d{2})\s*$", desc or "", re.M | re.I)
    if not m:
        return None
    try:
        return dt.date.fromisoformat(m.group(1)).isoformat()
    except ValueError:
        return None


def sync_from_trello(conn, trello, cfg):
    shipped = dismissed = 0
    for o in conn.execute("SELECT * FROM opportunities WHERE status='sent' AND card_id IS NOT NULL").fetchall():
        card = trello.get_card(o["card_id"])
        if card is not None and card.get("idList") == cfg.trello_done_list_id:
            date, source = _shipped_line(card.get("desc")), "card_line"
            if not date:
                moved = trello.last_move_date(o["card_id"], cfg.trello_done_list_id)
                date = (moved or dt.datetime.now(dt.timezone.utc)).astimezone(gsc.PACIFIC).date().isoformat()
                source = "trello_move"
            conn.execute("INSERT OR IGNORE INTO fixes (opportunity_id, site, page, ship_date, ship_date_source)"
                         " VALUES (?,?,?,?,?)", (o["id"], o["site"], o["page"], date, source))
            status = "done"
            shipped += 1
        elif card is None or card.get("closed"):
            status = "dismissed"
            dismissed += 1
        else:
            continue
        conn.execute("UPDATE opportunities SET status=?, status_changed_at=? WHERE id=?",
                     (status, db.utcnow(), o["id"]))
    return shipped, dismissed


def _totals(conn, site, start, end):
    rows = conn.execute("SELECT page, SUM(clicks) c, SUM(impressions) i FROM v_gsc_page WHERE site=?"
                        " AND date BETWEEN ? AND ? GROUP BY page", (site, start, end))
    return {r["page"]: (r["c"], r["i"]) for r in rows}


def measure_one(conn, cfg, fix):
    f = cfg.fix
    ship, w = dt.date.fromisoformat(fix["ship_date"]), f["window_days"]

    def iso(days):
        return (ship + dt.timedelta(days=days)).isoformat()

    r = {"before_start": iso(-w), "before_end": iso(-1), "after_start": iso(1), "after_end": iso(w)}
    before = _totals(conn, fix["site"], r["before_start"], r["before_end"])
    after = _totals(conn, fix["site"], r["after_start"], r["after_end"])
    cb, ib = before.get(fix["page"], (0, 0))
    ca, ia = after.get(fix["page"], (0, 0))
    r.update(clicks_before=cb, clicks_after=ca, impr_before=ib, impr_after=ia, group_size=0,
             group_median_growth=None, effect_clicks=None, included=0, exclusion_reason=None)
    if cb == 0 or ib < f["min_before_impressions"]:
        r["exclusion_reason"] = "too little data"
        return r
    excluded = {x["page"] for x in conn.execute(
        "SELECT page FROM fixes WHERE site=? AND ship_date BETWEEN ? AND ?",
        (fix["site"], iso(-f["exclusion_before_days"]), iso(w)))} | {fix["page"]}
    pop = {p: v for p, v in before.items() if v[0] >= 1 and v[1] >= 1 and p not in excluded}
    if len(pop) < max(2, f["min_comparison_pages"]):
        r["group_size"], r["exclusion_reason"] = len(pop), "too few comparison pages"
        return r
    cuts = statistics.quantiles([v[1] for v in pop.values()], n=4, method="inclusive")
    bounds = [float("-inf"), *cuts, float("inf")]
    q = next(i for i in range(4) if ib <= bounds[i + 1])
    group = [(after.get(p, (0, 0))[0] - v[0]) / v[0] for p, v in pop.items() if bounds[q] < v[1] <= bounds[q + 1]]
    r["group_size"] = len(group)
    if group:
        r["group_median_growth"] = statistics.median(group)
        r["effect_clicks"] = cb * ((ca - cb) / cb - r["group_median_growth"])
    if len(group) < f["min_comparison_pages"]:
        r["exclusion_reason"] = "too few comparison pages"
    else:
        r["included"] = 1
    return r


def measure_due(conn, cfg):
    """Measure every unmeasured fix whose after-window is fully final. Returns the measured rows."""
    done = []
    for fix in conn.execute("SELECT * FROM fixes WHERE measured_at IS NULL").fetchall():
        _, last = db.get_range(conn, fix["site"])
        due = dt.date.fromisoformat(fix["ship_date"]) + dt.timedelta(days=cfg.fix["window_days"])
        if not last or due.isoformat() > last:
            continue
        r = measure_one(conn, cfg, fix)
        sets = ", ".join(f"{k}=?" for k in r)
        conn.execute(f"UPDATE fixes SET {sets}, measured_at=? WHERE id=?", (*r.values(), db.utcnow(), fix["id"]))
        done.append({**dict(fix), **r})
    return done


def running_total(conn):
    return conn.execute("SELECT COALESCE(SUM(effect_clicks),0) FROM fixes WHERE included=1").fetchone()[0]
