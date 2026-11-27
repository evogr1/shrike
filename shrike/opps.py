"""Opportunity rules and lifecycle (design C5)."""

import datetime as dt
import hashlib
import json
import math
import re
import statistics

from . import db, templates

TYPES = ("striking_distance", "low_ctr", "decaying")


def _days(end, n):
    e = dt.date.fromisoformat(end)
    return (e - dt.timedelta(days=n - 1)).isoformat(), end


def band_of(position, bands):
    p = math.floor(position + 0.5)
    for i, (lo, hi) in enumerate(bands):
        if lo <= p <= hi:
            return i
    return None


def opportunity_id(site, type_, page, query=""):
    return hashlib.sha256(f"{site}|{type_}|{page}|{query}".encode()).hexdigest()[:16]


def _agg(conn, view, keys, site, start, end):
    cols = ", ".join(keys)
    return conn.execute(
        f"SELECT {cols}, SUM(clicks) clicks, SUM(impressions) impressions,"
        f" SUM(position * impressions) / NULLIF(SUM(impressions), 0) position FROM {view}"
        f" WHERE site = ? AND date BETWEEN ? AND ? GROUP BY {cols}", (site, start, end)).fetchall()


def expected_ctr(rows, o):
    """Per band: (ctr, source). The site's own median, or the fallback when it has too few queries."""
    per_band = [[] for _ in o["bands"]]
    for r in rows:
        if r["impressions"] >= o["expected_ctr_min_impr"]:
            b = band_of(r["position"], o["bands"])
            if b is not None:
                per_band[b].append(r["clicks"] / r["impressions"])
    out = []
    for i, vals in enumerate(per_band):
        if len(vals) >= o["min_band_pairs"] and statistics.median(vals) > 0:
            out.append((statistics.median(vals), "your site"))
        else:
            out.append((o["fallback_ctr"][i], "a generic benchmark"))
    return out


def striking_distance(site, rows, ctrs, o):
    out = []
    top = band_of(3, o["bands"])
    for r in rows:
        impr = r["impressions"]
        pos = math.floor(r["position"] + 0.5) if impr else 0
        if impr < o["sd_min_impr"] or not o["sd_min_pos"] <= pos <= o["sd_max_pos"]:
            continue
        ctr = r["clicks"] / impr
        target, src = ctrs[top]
        score = impr * (target - ctr)
        if score > 0:
            out.append(_opp(site, "striking_distance", r["page"], r["query"], score, {
                "impressions": impr, "clicks": r["clicks"], "ctr": ctr, "position": r["position"],
                "expected_ctr": target, "benchmark": src}))
    return out


def low_ctr(site, rows, ctrs, o):
    out = []
    for r in rows:
        impr = r["impressions"]
        if impr < o["lowctr_min_impr"]:
            continue
        b = band_of(r["position"], o["bands"])
        if b is None:
            continue
        ctr = r["clicks"] / impr
        exp, src = ctrs[b]
        if ctr < exp * o["lowctr_ratio"]:
            out.append(_opp(site, "low_ctr", r["page"], "", impr * (exp - ctr), {
                "impressions": impr, "clicks": r["clicks"], "ctr": ctr, "position": r["position"],
                "expected_ctr": exp, "benchmark": src}))
    return out


def decaying(site, now_rows, prev_rows, o):
    now = {r["page"]: r for r in now_rows}
    out = []
    for p in prev_rows:
        before = p["clicks"]
        if before < o["decay_min_clicks"] or before == 0:
            continue
        cur = now.get(p["page"])
        after = cur["clicks"] if cur else 0
        drop = (before - after) / before
        if drop >= o["decay_drop"]:
            out.append(_opp(site, "decaying", p["page"], "", before - after, {
                "clicks": after, "clicks_prev": before, "impressions": cur["impressions"] if cur else 0,
                "position": cur["position"] if cur else 0, "drop": drop}))
    return out


def _opp(site, type_, page, query, score, metrics):
    return {"id": opportunity_id(site, type_, page, query), "site": site, "type": type_, "page": page,
            "query": query, "score": float(score), "metrics": metrics}


def find(conn, site, cfg, end):
    o = cfg.opp
    start, _ = _days(end, 28)
    prev_end = (dt.date.fromisoformat(start) - dt.timedelta(days=1)).isoformat()
    prev_start, _ = _days(prev_end, 28)
    estart, _ = _days(end, o["expected_ctr_days"])
    ctrs = expected_ctr(_agg(conn, "v_gsc_page_query", ("page", "query"), site, estart, end), o)
    pq = _agg(conn, "v_gsc_page_query", ("page", "query"), site, start, end)
    pages = _agg(conn, "v_gsc_page", ("page",), site, start, end)
    prev = _agg(conn, "v_gsc_page", ("page",), site, prev_start, prev_end)
    found = striking_distance(site, pq, ctrs, o) + low_ctr(site, pages, ctrs, o) + decaying(site, pages, prev, o)
    for f in found:
        f["metrics"]["window_end"] = end
    return found


def _set_status(conn, oid, status):
    conn.execute("UPDATE opportunities SET status = ?, status_changed_at = ? WHERE id = ?",
                 (status, db.utcnow(), oid))


def upsert(conn, cfg, found, trello, run_id, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.replace(microsecond=0).isoformat()
    for f in found:
        row = conn.execute("SELECT status, status_changed_at FROM opportunities WHERE id = ?",
                           (f["id"],)).fetchone()
        m = json.dumps(f["metrics"])
        if row is None:
            conn.execute(
                "INSERT INTO opportunities (id, site, type, page, query, score, metrics, status, status_changed_at,"
                " first_seen, last_seen, last_detected_run) VALUES (?,?,?,?,?,?,?,'new',?,?,?,?)",
                (f["id"], f["site"], f["type"], f["page"], f["query"], f["score"], m, stamp, stamp, stamp, run_id))
            continue
        conn.execute("UPDATE opportunities SET score=?, metrics=?, last_seen=?, last_detected_run=?,"
                     " weeks_missing=0 WHERE id=?", (f["score"], m, stamp, run_id, f["id"]))
        if row["status"] in ("dismissed", "expired"):
            changed = dt.datetime.fromisoformat(row["status_changed_at"].replace("Z", "+00:00"))
            if now - changed >= dt.timedelta(weeks=cfg.opp["resend_after_weeks"]):
                _set_status(conn, f["id"], "new")
    seen = {f["id"] for f in found}
    for row in conn.execute("SELECT id, card_id, weeks_missing FROM opportunities WHERE status='sent'").fetchall():
        if row["id"] in seen:
            continue
        weeks = row["weeks_missing"] + 1
        conn.execute("UPDATE opportunities SET weeks_missing=? WHERE id=?", (weeks, row["id"]))
        if weeks >= cfg.opp["expire_after_weeks"]:
            if row["card_id"]:
                trello.close_card(row["card_id"])
            _set_status(conn, row["id"], "expired")


def load(row):
    d = dict(row)
    d["metrics"] = json.loads(d["metrics"])
    return d


def choose(candidates, o):
    out, per_type = [], {}
    for c in sorted(candidates, key=lambda c: c["score"], reverse=True):
        if per_type.get(c["type"], 0) < o["max_per_type"]:
            out.append(c)
            per_type[c["type"]] = per_type.get(c["type"], 0) + 1
        if len(out) >= o["brief_max"]:
            break
    return out


def select_for_brief(conn, cfg, run_id):
    rows = conn.execute("SELECT * FROM opportunities WHERE status='new' AND last_detected_run=?", (run_id,))
    return choose([load(r) for r in rows], cfg.opp)


def refresh_open_cards(conn, trello, run_id):
    rows = conn.execute("SELECT * FROM opportunities WHERE status='sent' AND last_detected_run=?"
                        " AND card_id IS NOT NULL", (run_id,)).fetchall()
    for r in rows:
        card = trello.get_card(r["card_id"])
        if not card or card.get("closed"):
            continue
        title, desc = templates.render_card(load(r))
        keep = re.search(r"^shipped:.*$", card.get("desc", ""), re.M | re.I)  # never lose the author's line
        if keep:
            desc += "\n\n" + keep.group(0)
        trello.update_card(r["card_id"], title, desc)
