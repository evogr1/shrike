"""shrike: the Phase 0 command line (backfill, nightly, setup, alert, render-units)."""

import argparse
import datetime as dt
import fcntl
import json
import os
import sys
from zoneinfo import ZoneInfo

from . import backup, baseline, brief, coverage, db, fixes, gsc, health, opps, setup_check, templates
from .config import load_config, load_secrets
from .errors import AuthError, ConfigError, QuotaError, SkError
from .health import JobContext
from .trello import Trello

# 10 = steps failed and were already alerted (treated as success by systemd via SuccessExitStatus=10 3).
# Any other non-zero code, including a Python traceback (1), fails the unit and triggers shrike-alert@.
EXIT_OK, EXIT_STEP_FAILED, EXIT_CONFIG, EXIT_RUNNING = 0, 10, 2, 3
WRITERS = ("backfill", "nightly", "weekly", "setup")


class AlreadyRunning(Exception):
    pass


def take_lock(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    fh = open(os.path.join(data_dir, "writer.lock"), "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        raise AlreadyRunning() from None
    return fh


# ---------------------------------------------------------------- pulling

def refresh_range(ctx, site):
    """Probe Search Console, set site_range, return (oldest, newest_final, recent_impressions)."""
    first_incomplete, recent = gsc.probe(ctx.gsc, site.property, auth_fix=_auth_fix(ctx, site))
    oldest, newest_final = gsc.available_range(first_incomplete)
    db.set_range(ctx.conn, site.name, first_date=oldest.isoformat(), last_final_date=newest_final.isoformat())
    return oldest.isoformat(), newest_final.isoformat(), recent


def _auth_fix(ctx, site):
    from . import google_auth

    email = google_auth.service_account_email(ctx.secrets) if ctx.secrets else "the service account"
    return f"add {email} as a Restricted user on {site.property} in Search Console"


def pull_site(ctx, site, oldest, recent):
    """Pull every missing (date, dims) for the site. Returns (pulled, deferred, failed)."""
    pulled = deferred = failed = 0
    first_error = None
    for date, dims in coverage.todo(ctx.conn, site.name, oldest):
        started = db.utcnow()
        try:
            rows, truncated = gsc.fetch_day(ctx.gsc, site.property, date, dims, "final",
                                            pause=ctx.cfg.pull_pause_seconds, auth_fix=_auth_fix(ctx, site))
        except (AuthError, QuotaError) as exc:
            db.record_failed_pull(ctx.conn, site.name, date, dims, exc, started)
            raise
        except SkError as exc:
            db.record_failed_pull(ctx.conn, site.name, date, dims, exc, started)
            failed += 1
            first_error = first_error or exc
            continue
        if dims == "site" and not rows and recent.get(date, 0) > 0:
            # Final site totals are empty while the 'all' probe shows impressions: not ready yet (C4).
            # Only site totals are checked: page and page+query rows can be legitimately empty on
            # low-traffic days because Google hides rare queries.
            db.record_failed_pull(ctx.conn, site.name, date, dims, "final data not ready", started)
            deferred += 1
            continue
        db.store_final(ctx.conn, site.name, date, dims, rows, truncated, started)
        pulled += 1
    if failed:
        raise SkError(f"{failed} pull(s) failed for {site.name}; first error: {first_error}",
                      getattr(first_error, "fix_step", None) or "the nightly job retries them")
    return pulled, deferred, failed


def do_backfill(ctx, target, only=None):
    ok = True
    for site in ctx.cfg.sites:
        if only and site.name != only:
            continue
        with health.step(ctx, f"pull:{site.name}") as s:
            oldest, _, recent = refresh_range(ctx, site)
            pull_site(ctx, site, oldest, recent)
            if not coverage.todo(ctx.conn, site.name, oldest):
                baseline.freeze(ctx.conn, site.name)
        ok &= s.ok
    with health.step(ctx, "backup") as s:
        backup.run(ctx.conn, ctx.cfg, target())
    ok &= s.ok
    return ok


def do_nightly(ctx, target):
    ok = True
    if ctx.cfg.phase >= 1:
        db.meta_set_once(ctx.conn, "phase1_seen_at", db.utcnow())
    for site in ctx.cfg.sites:
        with health.step(ctx, f"pull:{site.name}") as s:
            oldest, _, recent = refresh_range(ctx, site)
            pull_site(ctx, site, oldest, recent)
            if not coverage.todo(ctx.conn, site.name, oldest):
                baseline.freeze(ctx.conn, site.name)
        ok &= s.ok
    with health.step(ctx, "backup") as s:
        backup.run(ctx.conn, ctx.cfg, target())
    ok &= s.ok
    if ctx.cfg.phase >= 1:
        with health.step(ctx, "trello_sync") as s:
            fixes.sync_from_trello(ctx.conn, ctx.trello, ctx.cfg)
        ok &= s.ok
    with health.step(ctx, "checks") as s:
        health.run_checks(ctx)
    ok &= s.ok
    if health.undelivered(ctx) == 0:
        health.ping_dead_man(ctx.cfg.dead_man_url)
    return ok


def do_weekly(ctx, target):
    run_id, now = ctx.job_run_id, dt.datetime.now(ZoneInfo(ctx.cfg.timezone))
    ok = True
    with health.step(ctx, "opportunities") as s:
        found = []
        for site in ctx.cfg.sites:
            _, last = db.get_range(ctx.conn, site.name)
            if last:
                found += opps.find(ctx.conn, site.name, ctx.cfg, last)
        opps.upsert(ctx.conn, ctx.cfg, found, ctx.trello, run_id)
    ok &= s.ok
    with health.step(ctx, "refresh_cards") as s:
        opps.refresh_open_cards(ctx.conn, ctx.trello, run_id)
    ok &= s.ok
    measured = []
    with health.step(ctx, "measure") as s:
        measured = fixes.measure_due(ctx.conn, ctx.cfg)
    ok &= s.ok
    with health.step(ctx, "brief") as s:
        selected = opps.select_for_brief(ctx.conn, ctx.cfg, run_id)
        content = brief.build(ctx.conn, ctx.cfg, selected, measured)
        brief.send(ctx.conn, ctx.cfg, ctx.trello, content, now.date().isoformat())
    ok &= s.ok
    if now.day <= 7:
        with health.step(ctx, "verify_backup") as s:
            backup.verify_latest(ctx.conn, ctx.cfg, target())
        ok &= s.ok
    return ok


def preview(cfg, db_path):
    """Print what the weekly brief would contain. Reads only; sends and stores nothing."""
    conn = db.connect_ro(db_path)
    found = []
    for site in cfg.sites:
        _, last = db.get_range(conn, site.name)
        if last:
            found += opps.find(conn, site.name, cfg, last)
    selected = opps.choose(found, cfg.opp)
    title, text = brief.render_summary(cfg, brief.build(conn, cfg, selected, []), "preview")
    print(f"{title}\n{text}\n\n{len(found)} opportunities passed the thresholds.")
    for o in selected:
        card_title, desc = templates.render_card(o)
        print(f"\n== {card_title}\n" + desc.split("\n\nWhy:")[0])
    return len(found)


# ---------------------------------------------------------------- render-units

DOW = {"Mon": "Mon", "Tue": "Tue", "Wed": "Wed", "Thu": "Thu", "Fri": "Fri", "Sat": "Sat", "Sun": "Sun"}


def render_units(cfg, out_dir):
    tz = cfg.timezone
    day, hhmm = cfg.weekly.split()
    units = {
        "shrike-nightly.timer": ("Shrike nightly pull and backup", f"*-*-* {cfg.nightly}:00 {tz}",
                             "shrike-nightly.service"),
    }
    if cfg.phase >= 1:  # the weekly job exists only from Phase 1
        units["shrike-weekly.timer"] = ("Shrike weekly brief", f"{DOW[day]} *-*-* {hhmm}:00 {tz}", "shrike-weekly.service")
    written = []
    for name, (desc, cal, unit) in units.items():
        path = os.path.join(out_dir, name)
        with open(path, "w") as f:
            f.write(f"# Generated by `shrike render-units` from {cfg.path}. Do not edit by hand.\n"
                    f"[Unit]\nDescription={desc}\n\n[Timer]\nOnCalendar={cal}\nPersistent=true\n"
                    f"RandomizedDelaySec=300\nUnit={unit}\n\n[Install]\nWantedBy=timers.target\n")
        written.append(path)
    return written


# ---------------------------------------------------------------- main

def _make_ctx(cfg, secrets, need_gsc=True):
    conn = db.connect(cfg.db_path)
    db.migrate(conn, cfg.data_dir)
    gsc_client = None
    if need_gsc:
        from . import google_auth

        gsc_client = google_auth.searchconsole(google_auth.credentials(secrets))
    return JobContext(conn=conn, cfg=cfg, secrets=secrets, trello=Trello(secrets.trello_key, secrets.trello_token),
                      gsc=gsc_client)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="shrike")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--site")
    sub.add_parser("nightly")
    w = sub.add_parser("weekly")
    w.add_argument("--dry-run", action="store_true")
    sub.add_parser("setup")
    a = sub.add_parser("alert")
    a.add_argument("--unit", required=True)
    r = sub.add_parser("render-units")
    r.add_argument("--out", default="/etc/systemd/system")
    args = ap.parse_args(argv)

    try:
        cfg = load_config()
        if args.cmd == "render-units":
            for p in render_units(cfg, args.out):
                print(p)
            return EXIT_OK
        if args.cmd == "weekly" and args.dry_run:
            preview(cfg, cfg.db_path)
            return EXIT_OK
        secrets = load_secrets("alert" if args.cmd == "alert" else "jobs")
    except ConfigError as e:
        print(f"config error: {e}\nfix: {e.fix_step}", file=sys.stderr)
        return EXIT_CONFIG

    if args.cmd == "alert":
        conn = db.connect(cfg.db_path)
        db.migrate(conn, cfg.data_dir)
        ctx = JobContext(conn=conn, cfg=cfg, secrets=secrets, trello=Trello(secrets.trello_key, secrets.trello_token))
        health.alert(ctx, "unit_failed", args.unit, f"systemd unit {args.unit} crashed, was killed or hit a config error",
                     f"run: journalctl -u {args.unit} -n 100, and see docs/OPERATIONS.md")
        return EXIT_OK

    if args.cmd == "weekly" and cfg.phase == 0:
        print("Phase 1 not enabled (general.phase = 0)", file=sys.stderr)
        return EXIT_CONFIG

    try:
        lock = take_lock(cfg.data_dir)
    except AlreadyRunning:
        print("already running", file=sys.stderr)
        if args.cmd == "nightly":
            health.ping_dead_man(cfg.dead_man_url)  # VM alive, a writer is running (C14)
        return EXIT_RUNNING

    try:
        if args.cmd == "setup":
            ctx = _make_ctx(cfg, secrets, need_gsc=False)
            checks = setup_check.full_report(ctx)
            report = {"saved_at": db.utcnow(), "checks": [c.__dict__ for c in checks]}
            path = os.path.join(cfg.data_dir, "setup_report.json")
            with open(path + ".tmp", "w") as f:
                json.dump(report, f, indent=2)
            os.replace(path + ".tmp", path)
            for c in checks:
                print(f"[{'ok' if c.ok else 'FAIL'}] {c.name}: {c.detail}" + ("" if c.ok else f"\n       fix: {c.fix_step}"))
            return EXIT_OK if all(c.ok or c.warning for c in checks) else EXIT_STEP_FAILED

        ctx = _make_ctx(cfg, secrets, need_gsc=args.cmd != "weekly")
        health.start_job(ctx, args.cmd)

        def target():
            return backup.make_target(cfg, secrets)

        if args.cmd == "backfill":
            ok = do_backfill(ctx, target, args.site)
        elif args.cmd == "weekly":
            ok = do_weekly(ctx, target)
        else:
            ok = do_nightly(ctx, target)
        health.finish_job(ctx, ok)
        return EXIT_OK if ok else EXIT_STEP_FAILED
    except SkError as e:
        # Raised outside a step, so nothing was alerted: exit 1 fails the unit and triggers shrike-alert@.
        print(f"error: {e}\nfix: {e.fix_step}", file=sys.stderr)
        return 1
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
