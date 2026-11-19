"""Setup check: tests every part and gives one fix step for each broken part."""

import datetime as dt
import json
import os
from dataclasses import dataclass

from . import backup, db, gsc
from .errors import SkError


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix_step: str = ""
    warning: bool = False   # shown, but does not fail setup
    checked_at: str = ""


def _check(name, fn):
    try:
        ok, detail, fix = fn()
        return Check(name, ok, detail, fix or "", checked_at=db.utcnow())
    except SkError as e:
        return Check(name, False, str(e), e.fix_step or "", checked_at=db.utcnow())
    except Exception as e:
        return Check(name, False, repr(e)[:300], "see the journal for details", checked_at=db.utcnow())


def full_report(ctx, gsc_client=None, drive_target=None):
    cfg, sec = ctx.cfg, ctx.secrets
    out = [Check("config", True, f"loaded {cfg.path} ({len(cfg.sites)} site(s))", checked_at=db.utcnow()),
           Check("secrets", True, "env file and key file permissions are private", checked_at=db.utcnow()),
           Check("database", True, f"schema v{db.schema_version(ctx.conn)} at {cfg.db_path}", checked_at=db.utcnow())]

    client = gsc_client
    if client is None:
        def make():
            from . import google_auth

            return google_auth.searchconsole(google_auth.credentials(sec))
        try:
            client = make()
        except Exception as e:
            out.append(Check("service account", False, f"could not load the key: {e!r}"[:300],
                             "check SHRIKE_SERVICE_ACCOUNT_FILE; if the key can't be created, see docs/SETUP.md "
                             "(iam.disableServiceAccountKeyCreation)", checked_at=db.utcnow()))
    if client is not None:
        from .jobs import _auth_fix

        for s in cfg.sites:
            def probe(s=s):
                fid, _ = gsc.probe(client, s.property, auth_fix=_auth_fix(ctx, s))
                return True, f"Search Console readable; newest final date {fid - dt.timedelta(days=1)}", None
            out.append(_check(f"search console: {s.name}", probe))

    def trello_lists():
        names = []
        for label, lid in (("alert", cfg.trello_alert_list_id),) + (
                (("inbox", cfg.trello_inbox_list_id), ("done", cfg.trello_done_list_id)) if cfg.phase >= 1 else ()):
            if not lid:
                return False, f"trello.{label}_list_id is empty", f"set trello.{label}_list_id in config.toml"
            lst = ctx.trello.get_list(lid)
            if not lst:
                return False, f"Trello list {lid} ({label}) not found", f"check trello.{label}_list_id"
            names.append(f"{label}={lst.get('name', lid)}")
        cid = ctx.trello.create_card(cfg.trello_alert_list_id, "[Shrike] setup test (safe to ignore)",
                                     "Posted and deleted by shrike setup.")
        ctx.trello.delete_card(cid)
        return True, "lists readable and alert path works (" + ", ".join(names) + ")", None
    out.append(_check("trello", trello_lists))

    def backup_target():
        t = drive_target or backup.make_target(cfg, sec)
        return backup.test_target(t)
    c = _check("backup target", backup_target)
    if cfg.backup_target == "local" and not c.ok and "G1 not met" in c.detail:
        c.warning = True
    out.append(c)

    if cfg.dead_man_url:
        out.append(Check("dead-man check", True, "dead_man_url is set", checked_at=db.utcnow()))
    else:
        out.append(Check("dead-man check", False, "general.dead_man_url is empty, so G5 is not met",
                         "create a free healthchecks.io check (26 h period) and paste its ping URL",
                         warning=True, checked_at=db.utcnow()))

    last = ctx.conn.execute("SELECT job, status, finished_at FROM runs WHERE step IS NULL"
                            " ORDER BY id DESC LIMIT 1").fetchone()
    out.append(Check("last run", True, f"{last['job']} {last['status']} at {last['finished_at']}" if last
                     else "no runs yet", checked_at=db.utcnow()))
    return out


def readonly_report(cfg, data_dir):
    """For the Phase 1 server: the saved report, never writing anything."""
    path = os.path.join(data_dir, "setup_report.json")
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"saved_at": None, "checks": [], "note": "run shrike setup"}
