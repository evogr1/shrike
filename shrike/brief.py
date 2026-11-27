"""The weekly brief: one summary card plus one card per opportunity."""

import datetime as dt

from . import baseline, coverage, db, fixes, templates
from .errors import SkError


def header(conn, cfg):
    lines = []
    for s in cfg.sites:
        _, last = db.get_range(conn, s.name)
        lines.append(f"{s.name}: data final up to {last or 'never'}, {coverage.missing_days(conn, s.name)} day(s) "
                     f"missing, {len(coverage.truncated_days(conn, s.name))} truncated")
    now = dt.datetime.now(dt.timezone.utc)
    week = (now - dt.timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    failed = conn.execute("SELECT COUNT(*) FROM runs WHERE step IS NOT NULL AND status='error' AND started_at>?",
                          (week,)).fetchone()[0]
    last = conn.execute("SELECT MAX(finished_at) FROM runs WHERE step='backup' AND status='ok'").fetchone()[0]
    age = "never"
    if last:
        age = f"{(now - dt.datetime.fromisoformat(last.replace('Z', '+00:00'))).total_seconds() / 3600:.0f} h ago"
    lines.append(f"Failed steps in 7 days: {failed}. Last backup: {age}.")
    if cfg.backup_target == "local":
        lines.append("Backups are written on this machine (G1 counts only an off-host target Shrike can check).")
    return lines


def build(conn, cfg, selected, measured):
    return {"header": header(conn, cfg),
            "comparisons": [c for c in (baseline.compare(conn, s.name) for s in cfg.sites) if c],
            "opportunities": selected, "measured": measured, "running_total": fixes.running_total(conn)}


def render_summary(cfg, b, day):
    out = [*b["header"], "", "Last 28 days against the starting baseline:"]
    for c in b["comparisons"]:
        def pct(v):
            return "n/a" if v is None else f"{v:+.0f}%"
        out.append(f"- {c['site']}: {c['current']['clicks']} clicks ({pct(c['clicks_pct'])}), "
                   f"{c['current']['impressions']} impressions ({pct(c['impressions_pct'])})")
    n = len(b["opportunities"])
    out += ["", f"New fixes this week: {n}."]
    if n < cfg.opp["brief_min"]:
        out.append("Fewer than usual: only this many passed the thresholds in config.toml.")
    if b["measured"]:
        out += ["", "Measured fixes:"]
        for m in b["measured"]:
            effect = "n/a" if m["effect_clicks"] is None else f"{m['effect_clicks']:+.0f} clicks per 28 days"
            note = "" if m["included"] else f" (not counted: {m['exclusion_reason']})"
            out.append(f"- {m['page']}: {m['clicks_before']} -> {m['clicks_after']} clicks, effect {effect}{note}")
    out += ["", f"Running total of measured gains: {b['running_total']:+.0f} clicks per 28 days."]
    return f"[Shrike] Week of {day}", "\n".join(out)


def send(conn, cfg, trello, b, day):
    """Post the summary, then each fix card. A card that fails leaves its opportunity 'new'."""
    trello.create_card(cfg.trello_inbox_list_id, *render_summary(cfg, b, day))
    failed = []
    for o in b["opportunities"]:
        try:
            card = trello.create_card(cfg.trello_inbox_list_id, *templates.render_card(o))
        except SkError as e:
            failed.append(e)
            continue
        conn.execute("UPDATE opportunities SET status='sent', status_changed_at=?, card_id=? WHERE id=?",
                     (db.utcnow(), card, o["id"]))
    if failed:
        raise SkError(f"{len(failed)} brief card(s) failed: {failed[0]}", failed[0].fix_step)
