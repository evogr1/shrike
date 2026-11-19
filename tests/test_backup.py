import datetime as dt
import gzip
import os
import threading
import unittest

from sk import backup, db
from sk.errors import SkError
from tests.fakes import FakeDrive, make_ctx, media_bytes, tmpdir

UTC = dt.timezone.utc


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.t = tmpdir()
        self.ctx = make_ctx(self.t)
        db.set_range(self.ctx.conn, "ex", first_date="2026-01-01", last_final_date="2026-01-03")
        for d in ("2026-01-01", "2026-01-02"):
            db.store_final(self.ctx.conn, "ex", d, "site", [], False, db.utcnow())

    def test_snapshot_during_writes_restores_intact(self):
        stop = threading.Event()
        wconn = db.connect(self.ctx.cfg.db_path)

        def writer():
            i = 0
            while not stop.is_set():
                wconn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, 'x')", (f"k{i}",))
                i += 1
        th = threading.Thread(target=writer)
        th.start()
        try:
            name = backup.run(self.ctx.conn, self.ctx.cfg, backup.LocalTarget(self.ctx.cfg.local_path))
        finally:
            stop.set()
            th.join()
        raw = os.path.join(self.t, "r.sqlite")
        with gzip.open(os.path.join(self.ctx.cfg.local_path, name)) as fi, open(raw, "wb") as fo:
            fo.write(fi.read())
        r = db.connect(raw)
        self.assertEqual(r.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_keep_set_union_rule(self):
        now = dt.datetime(2026, 11, 19, 4, 0, tzinfo=UTC)
        names = [backup.backup_name(now - dt.timedelta(days=i)) for i in range(400)]
        keep = backup.keep_set(names, 30, 12, now)
        # 30 daily (Oct 21 - Nov 19) + newest of each of the 10 older months (Dec 2025 - Sep 2026).
        # Nov's and Oct's newest files are already inside the daily window.
        self.assertEqual(len(keep), 40)
        self.assertIn(backup.backup_name(now), keep)

    def test_local_verify_and_corruption(self):
        target = backup.LocalTarget(self.ctx.cfg.local_path)
        backup.run(self.ctx.conn, self.ctx.cfg, target)
        self.assertTrue(backup.verify_latest(self.ctx.conn, self.ctx.cfg, target))
        _, fid, name = backup.latest(target)
        with open(os.path.join(self.ctx.cfg.local_path, fid), "wb") as f:
            f.write(b"not a gzip")
        with self.assertRaises(SkError):
            backup.verify_latest(self.ctx.conn, self.ctx.cfg, target)

    def test_verify_detects_backup_behind(self):
        target = backup.LocalTarget(self.ctx.cfg.local_path)
        backup.run(self.ctx.conn, self.ctx.cfg, target, now=dt.datetime(2030, 1, 1, tzinfo=UTC))
        # live gains a final day whose pull 'finished' before the backup time -> backup should have it
        self.ctx.conn.execute("INSERT INTO pulls (site,date,dims,data_state,status,started_at,finished_at)"
                              " VALUES ('ex','2026-01-03','site','final','ok','2020-01-01T00:00:00Z',"
                              "'2020-01-01T00:00:00Z')")
        with self.assertRaises(SkError):
            backup.verify_latest(self.ctx.conn, self.ctx.cfg, target)

    def test_drive_calls_all_pass_supports_all_drives_and_prune_trashes(self):
        fake = FakeDrive()
        target = backup.DriveTarget(fake, "fold", media_factory=media_bytes)
        now = dt.datetime(2026, 11, 19, 4, 0, tzinfo=UTC)
        for i in range(35, -1, -1):
            backup.run(self.ctx.conn, self.ctx.cfg, target, now=now - dt.timedelta(days=i))
        self.assertTrue(backup.verify_latest(self.ctx.conn, self.ctx.cfg, target))
        for op, kw in fake.calls:
            self.assertTrue(kw.get("supportsAllDrives"), op)
        lists = [kw for op, kw in fake.calls if op == "list"]
        self.assertTrue(all(kw["includeItemsFromAllDrives"] and kw["corpora"] == "drive" for kw in lists))
        self.assertFalse(any(op == "delete" for op, _ in fake.calls))
        live = [v for v in fake.store.values() if not v[2]]
        self.assertLessEqual(len(live), 31)

    def test_test_target_detects_role_too_strong(self):
        ok, _, _ = backup.test_target(backup.DriveTarget(FakeDrive(), "fold", media_factory=media_bytes))
        self.assertTrue(ok)
        ok, detail, fix = backup.test_target(backup.DriveTarget(FakeDrive(allow_permanent_delete=True), "fold",
                                                                media_factory=media_bytes))
        self.assertFalse(ok)
        self.assertIn("Content Manager", fix)

    def test_local_target_reports_g1_not_met(self):
        ok, detail, _ = backup.test_target(backup.LocalTarget(self.ctx.cfg.local_path))
        self.assertFalse(ok)
        self.assertIn("G1 not met", detail)


if __name__ == "__main__":
    unittest.main()
