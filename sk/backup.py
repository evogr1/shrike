"""Nightly backups to a Google Shared Drive folder or a local folder (design C13)."""

import datetime as dt
import gzip
import os
import re
import shutil
import sqlite3
import tempfile

from . import db
from .errors import AuthError, SkError, UpstreamError

NAME_RE = re.compile(r"^sk-(\d{8}T\d{4}Z)\.sqlite\.gz$")


def backup_name(now):
    return f"sk-{now.strftime('%Y%m%dT%H%MZ')}.sqlite.gz"


def parse_time(name):
    m = NAME_RE.match(name)
    if not m:
        return None
    return dt.datetime.strptime(m.group(1), "%Y%m%dT%H%MZ").replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------- targets

class LocalTarget:
    kind = "local"

    def __init__(self, path):
        self.path = path

    def upload(self, src, name):
        os.makedirs(self.path, exist_ok=True)
        shutil.copyfile(src, os.path.join(self.path, name))

    def list(self):
        if not os.path.isdir(self.path):
            return []
        return [(n, n) for n in os.listdir(self.path) if NAME_RE.match(n)]

    def trash(self, file_id):
        os.remove(os.path.join(self.path, file_id))

    def download(self, file_id, dest):
        shutil.copyfile(os.path.join(self.path, file_id), dest)


class DriveTarget:
    """Every call passes supportsAllDrives=True (required for Shared Drive items)."""

    kind = "gdrive"

    def __init__(self, service, folder_id, media_factory=None):
        self.svc = service
        self.folder_id = folder_id
        self._drive_id = None
        self._media = media_factory

    def _wrap(self, fn, what):
        try:
            return fn()
        except SkError:
            raise
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if str(status) in ("401", "403", "404"):
                raise AuthError(f"Drive refused {what} (HTTP {status})",
                                "add the service account as Content Manager on the backup folder") from exc
            raise UpstreamError(f"Drive {what} failed: {exc!r}"[:500], "check the journal for details") from exc

    def drive_id(self):
        if self._drive_id is None:
            meta = self._wrap(lambda: self.svc.files().get(
                fileId=self.folder_id, fields="driveId", supportsAllDrives=True).execute(), "folder lookup")
            self._drive_id = meta.get("driveId") or ""
        return self._drive_id

    def upload(self, src, name):
        if self._media is not None:
            media = self._media(src)
        else:
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(src, mimetype="application/gzip", resumable=True, chunksize=8 * 1024 * 1024)
        body = {"name": name, "parents": [self.folder_id]}
        return self._wrap(lambda: self.svc.files().create(
            body=body, media_body=media, fields="id", supportsAllDrives=True).execute(), "upload")["id"]

    def list(self):
        drive_id = self.drive_id()
        q = f"'{self.folder_id}' in parents and trashed = false and name contains 'sk-'"
        out, token = [], None
        while True:
            kw = dict(q=q, includeItemsFromAllDrives=True, supportsAllDrives=True,
                      fields="nextPageToken, files(id, name)", pageSize=1000)
            if drive_id:
                kw.update(corpora="drive", driveId=drive_id)
            if token:
                kw["pageToken"] = token
            resp = self._wrap(lambda kw=kw: self.svc.files().list(**kw).execute(), "list")
            out += [(f["id"], f["name"]) for f in resp.get("files", []) if NAME_RE.match(f["name"])]
            token = resp.get("nextPageToken")
            if not token:
                return out

    def trash(self, file_id):
        self._wrap(lambda: self.svc.files().update(
            fileId=file_id, body={"trashed": True}, supportsAllDrives=True).execute(), "trash")

    def download(self, file_id, dest):
        data = self._wrap(lambda: self.svc.files().get_media(fileId=file_id, supportsAllDrives=True).execute(),
                          "download")
        with open(dest, "wb") as f:
            f.write(data)

    def try_permanent_delete(self, file_id):
        """True if the delete succeeded (bad: the role is too strong)."""
        try:
            self.svc.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            return True
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if str(status) == "403":
                return False
            raise


def make_target(cfg, secrets, drive_service=None):
    if cfg.backup_target == "local":
        return LocalTarget(cfg.local_path)
    if not cfg.gdrive_folder_id:
        raise SkError("backup.gdrive_folder_id is empty", "copy the Shared Drive folder id into config.toml")
    if drive_service is None:
        from . import google_auth

        drive_service = google_auth.drive(google_auth.credentials(secrets))
    return DriveTarget(drive_service, cfg.gdrive_folder_id)


# ---------------------------------------------------------------- operations

def run(conn, cfg, target, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    tmp = os.path.join(cfg.data_dir, "tmp")
    os.makedirs(tmp, exist_ok=True)
    name = backup_name(now)
    raw = os.path.join(tmp, "snapshot.sqlite")
    gz = os.path.join(tmp, name)
    try:
        db.snapshot(conn, raw)
        with open(raw, "rb") as fi, gzip.open(gz, "wb", compresslevel=6) as fo:
            shutil.copyfileobj(fi, fo, 1024 * 1024)
        target.upload(gz, name)
    finally:
        for p in (raw, gz):
            if os.path.exists(p):
                os.remove(p)
    prune(target, cfg, now)
    return name


def keep_set(names, keep_daily, keep_monthly, now):
    """Names to keep: newest per UTC day for the last keep_daily days, plus newest per UTC month
    for the last keep_monthly months."""
    timed = sorted(((parse_time(n), n) for n in names if parse_time(n)), reverse=True)
    today = now.astimezone(dt.timezone.utc).date()
    first_day = today - dt.timedelta(days=keep_daily - 1)
    months, y, m = [], today.year, today.month
    for _ in range(keep_monthly):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    keep, seen_day, seen_month = set(), set(), set()
    for t, n in timed:
        d = t.date()
        if first_day <= d <= today and d not in seen_day:
            seen_day.add(d)
            keep.add(n)
        ym = (d.year, d.month)
        if ym in months and ym not in seen_month:
            seen_month.add(ym)
            keep.add(n)
    return keep


def prune(target, cfg, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    files = target.list()
    keep = keep_set([n for _, n in files], cfg.keep_daily, cfg.keep_monthly, now)
    removed = []
    for fid, name in files:
        if name not in keep:
            target.trash(fid)
            removed.append(name)
    return removed


def latest(target):
    best = None
    for fid, name in target.list():
        t = parse_time(name)
        if t and (best is None or t > best[0]):
            best = (t, fid, name)
    return best


def verify_latest(conn, cfg, target):
    """Download the newest backup, check integrity and that its coverage isn't behind (C13)."""
    best = latest(target)
    if not best:
        raise SkError("no backup found to verify", "check that the nightly backup step succeeds")
    when, fid, name = best
    tmpdir = tempfile.mkdtemp(dir=os.path.join(cfg.data_dir, "tmp") if os.path.isdir(
        os.path.join(cfg.data_dir, "tmp")) else None)
    try:
        gz = os.path.join(tmpdir, name)
        raw = os.path.join(tmpdir, "restore.sqlite")
        target.download(fid, gz)
        try:
            with gzip.open(gz, "rb") as fi, open(raw, "wb") as fo:
                shutil.copyfileobj(fi, fo, 1024 * 1024)
            bconn = sqlite3.connect(raw)
            ok = bconn.execute("PRAGMA integrity_check").fetchone()[0]
        except Exception as exc:
            raise SkError(f"backup {name} is unreadable: {exc!r}", "check disk space and the backup target") from exc
        if ok != "ok":
            raise SkError(f"backup {name} failed integrity_check: {ok}", "check disk space and the backup target")
        bconn.row_factory = sqlite3.Row
        since = when.isoformat().replace("+00:00", "Z")
        for s in cfg.sites:
            b = bconn.execute("SELECT COUNT(*) FROM v_coverage WHERE site = ? AND state IN ('final','truncated')",
                              (s.name,)).fetchone()[0]
            live = conn.execute("SELECT COUNT(*) FROM v_coverage WHERE site = ? AND state IN ('final','truncated')",
                                (s.name,)).fetchone()[0]
            newer = conn.execute("SELECT COUNT(*) FROM pulls WHERE site = ? AND status = 'ok' AND finished_at > ?",
                                 (s.name, since)).fetchone()[0]
            if b < live - newer:
                raise SkError(f"backup {name} is missing data for {s.name} ({b} vs {live - newer} expected)",
                              "run a manual backup and check it again")
        bconn.close()
        return name
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_target(target):
    """Setup-check probe. Returns (ok, detail, fix_step)."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".gz")
    tmp.write(b"\0")
    tmp.close()
    name = "sk-19700101T0000Z.sqlite.gz"
    try:
        if target.kind == "local":
            target.upload(tmp.name, name)
            target.trash(name)
            return False, "local backup target works, but backups stay on this machine (G1 not met)", \
                "use a Google Shared Drive target for off-host backups"
        fid = target.upload(tmp.name, name)
        if target.try_permanent_delete(fid):
            return False, "the service account can permanently delete backups (role too strong)", \
                "change the service account to Content Manager, not Manager, on the backup folder"
        target.trash(fid)
        return True, "upload works and permanent delete is refused (Content Manager)", None
    finally:
        os.remove(tmp.name)
