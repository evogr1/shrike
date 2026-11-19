"""Run tracking, alerts, health checks and the dead-man ping (design C11)."""

import datetime as dt
import sys
import traceback
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from . import coverage, db, gsc
from .errors import AuthError, QuotaError, SkError
from .trello import scrub


@dataclass
class JobContext:
    conn: object
    cfg: object
    secrets: object
    trello: object
    gsc: object = None
    job_run_id: int = 0
    job: str = ""


@dataclass
class Problem:
    kind: str
    subject: str
    message: str
    fix_step: str
    once: bool = False


class StepResult:
    ok = False
    error = None


def local_day(cfg, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.astimezone(ZoneInfo(cfg.timezone)).date().isoformat()


def start_job(ctx, job):
    cur = ctx.conn.execute("INSERT INTO runs (job, status, started_at) VALUES (?, 'running', ?)", (job, db.utcnow()))
    ctx.job_run_id, ctx.job = cur.lastrowid, job
    return ctx.job_run_id


def finish_job(ctx, ok):
    ctx.conn.execute("UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
                     ("ok" if ok else "error", db.utcnow(), ctx.job_run_id))


def undelivered(ctx):
    r = ctx.conn.execute("SELECT undelivered_alerts FROM runs WHERE id = ?", (ctx.job_run_id,)).fetchone()
    return r[0] if r else 0


@contextmanager
def step(ctx, name):
    """with step(ctx, "pull") as s: ...   then read s.ok. Exceptions are recorded, alerted and swallowed."""
    s = StepResult()
    cur = ctx.conn.execute(
        "INSERT INTO runs (job, step, parent_id, status, started_at) VALUES (?, ?, ?, 'running', ?)",
        (ctx.job, name, ctx.job_run_id, db.utcnow()))
    row_id = cur.lastrowid
    try:
        yield s
        s.ok = True
        ctx.conn.execute("UPDATE runs SET status = 'ok', finished_at = ? WHERE id = ?", (db.utcnow(), row_id))
    except Exception as exc:
        s.ok, s.error = False, exc
        if ctx.conn.in_transaction:
            ctx.conn.execute("ROLLBACK")
        msg = scrub(str(exc) or repr(exc))
        ctx.conn.execute("UPDATE runs SET status = 'error', finished_at = ?, error = ? WHERE id = ?",
                         (db.utcnow(), msg[:2000], row_id))
        fix = getattr(exc, "fix_step", None) or "check the journal: journalctl -u sk-" + ctx.job
        if isinstance(exc, AuthError):
            alert(ctx, "auth", name, msg, fix)
        elif isinstance(exc, QuotaError):
            alert(ctx, "quota", name, msg, fix)
        else:
            if not isinstance(exc, SkError):
                print(scrub("".join(traceback.format_exception(exc))), file=sys.stderr)
            alert(ctx, "step_failed", f"{ctx.job}:{name}", msg, fix)


def alert(ctx, kind, subject, message, fix_step, once=False):
    """Send one Trello alert card, deduplicated per (kind, subject, day) or once ever."""
    day = "once" if once else local_day(ctx.cfg)
    conn = ctx.conn
    row = conn.execute("SELECT id, delivered FROM events WHERE kind = ? AND subject = ? AND day = ?",
                       (kind, subject, day)).fetchone()
    if row and row["delivered"]:
        return False
    if not row:
        cur = conn.execute(
            "INSERT INTO events (kind, subject, day, message, delivered, created_at) VALUES (?, ?, ?, ?, 0, ?)",
            (kind, subject, day, message, db.utcnow()))
        event_id = cur.lastrowid
    else:
        event_id = row["id"]
    title = f"[Search Kestrel] {kind}: {subject}"
    desc = f"{message}\n\nFix: {fix_step or 'see docs/OPERATIONS.md'}\n\n({db.utcnow()})"
    try:
        if ctx.trello is None or not ctx.cfg.trello_alert_list_id:
            raise SkError("no Trello alert list configured")
        card_id = ctx.trello.create_card(ctx.cfg.trello_alert_list_id, title, desc)
        conn.execute("UPDATE events SET delivered = 1, card_id = ? WHERE id = ?", (card_id, event_id))
        return True
    except Exception as exc:
        print(scrub(f"ALERT NOT DELIVERED ({exc!r}): {title}: {message} | fix: {fix_step}"), file=sys.stderr)
        if ctx.job_run_id:
            conn.execute("UPDATE runs SET undelivered_alerts = undelivered_alerts + 1 WHERE id = ?",
                         (ctx.job_run_id,))
        return False


def _hours_since(iso, now):
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (now - t).total_seconds() / 3600


def checks(ctx, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    cfg, conn = ctx.cfg, ctx.conn
    out = []
    for s in cfg.sites:
        first, last = db.get_range(conn, s.name)
        if not last:
            continue
        oldest = gsc.oldest_for(last)
        cutoff = (dt.date.fromisoformat(last) - dt.timedelta(days=cfg.gap_days)).isoformat()
        gaps = [d for d in coverage.gaps_older_than(conn, s.name, cutoff) if d >= oldest]
        if gaps:
            out.append(Problem("gap", s.name, f"{len(gaps)} day(s) still missing for {s.name}, oldest {gaps[0]}",
                               "check earlier alerts for the cause; the nightly job retries missing days"))
        for d in coverage.truncated_days(conn, s.name):
            out.append(Problem("truncated", f"{s.name}:{d}",
                               f"{s.name} {d} hit the API's 50,000-row daily cap; some long-tail rows are missing",
                               "nothing to do; page and site totals are complete", once=True))
        for d in coverage.expired(conn, s.name, oldest):
            out.append(Problem("expired", f"{s.name}:{d}",
                               f"{s.name} {d} expired from Search Console before it was saved",
                               "nothing can recover it; check why earlier pulls failed", once=True))
        om = coverage.oldest_missing(conn, s.name, oldest)
        if om and (dt.date.fromisoformat(om) - dt.date.fromisoformat(oldest)).days < cfg.expiry_warn_days:
            out.append(Problem("expiry_warning", s.name,
                               f"{s.name} {om} is missing and expires from Search Console within "
                               f"{cfg.expiry_warn_days} days",
                               "run the backfill now: systemctl start sk-backfill.service"))
    last_backup = conn.execute("SELECT MAX(finished_at) FROM runs WHERE step = 'backup' AND status = 'ok'").fetchone()[0]
    first_run = conn.execute("SELECT MIN(started_at) FROM runs WHERE step IS NULL").fetchone()[0]
    ref = last_backup or first_run
    if ref and _hours_since(ref, now) > cfg.backup_max_hours:
        out.append(Problem("backup_stale", cfg.backup_target,
                           f"no successful backup in {cfg.backup_max_hours} hours",
                           "check the backup step's error in earlier alerts"))
    if cfg.phase >= 1:
        last_weekly = conn.execute(
            "SELECT MAX(finished_at) FROM runs WHERE job = 'weekly' AND step IS NULL AND status = 'ok'").fetchone()[0]
        anchor = max([x for x in (last_weekly, db.meta_get(conn, "phase1_seen_at")) if x], default=None)
        if anchor and _hours_since(anchor, now) > cfg.weekly_max_days * 24:
            out.append(Problem("weekly_missing", "weekly", f"no successful weekly run in {cfg.weekly_max_days} days",
                               "check: systemctl status sk-weekly.timer sk-weekly.service"))
    return out


def run_checks(ctx, now=None):
    problems = checks(ctx, now)
    for p in problems:
        alert(ctx, p.kind, p.subject, p.message, p.fix_step, once=p.once)
    return problems


def ping_dead_man(url, timeout=10):
    if not url:
        return False
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception as exc:
        print(f"dead-man ping failed: {exc!r}", file=sys.stderr)
        return False
