import datetime as dt
import os
import subprocess
import sys
import unittest
from unittest import mock

from shrike import backup, gsc, health, jobs
from tests.fakes import FakeSearchConsole, FakeTrello, make_ctx, make_data, tmpdir

P = "sc-domain:ex.com"
FID = dt.date(2026, 3, 10)          # first incomplete date -> newest final 2026-03-09
NEWEST = dt.date(2026, 3, 9)
OLDEST = NEWEST - dt.timedelta(days=482)


def client():
    return FakeSearchConsole(FID, make_data(P, OLDEST - dt.timedelta(days=10), FID + dt.timedelta(days=2)))


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.t = tmpdir()
        patcher = mock.patch.object(gsc, "today_pacific", lambda: FID + dt.timedelta(days=2))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.trello = FakeTrello()
        self.ctx = make_ctx(self.t, trello=self.trello, gsc_client=client())
        health.start_job(self.ctx, "backfill")
        self.target = lambda: backup.LocalTarget(self.ctx.cfg.local_path)

    def pulled(self, date=None):
        q = "SELECT date, dims FROM pulls WHERE status='ok'" + (" AND date=?" if date else "") + " ORDER BY id"
        return self.ctx.conn.execute(q, (date,) if date else ()).fetchall()

    def test_fresh_backfill_pulls_everything_oldest_first_and_backs_up(self):
        self.assertTrue(jobs.do_backfill(self.ctx, self.target))
        rows = self.pulled()
        self.assertEqual(len(rows), 483 * 3)
        self.assertEqual(rows[0]["date"], OLDEST.isoformat())
        self.assertEqual([r["dims"] for r in rows[:3]], ["site", "page", "page_query"])
        self.assertEqual(self.ctx.conn.execute("SELECT first_date, last_final_date FROM site_range").fetchone()[:],
                         (OLDEST.isoformat(), NEWEST.isoformat()))
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM baselines").fetchone()[0], 1)
        self.assertEqual(len(backup.LocalTarget(self.ctx.cfg.local_path).list()), 1)

    def test_baseline_waits_for_28_final_days_and_never_changes(self):
        self.ctx.gsc.data = make_data(P, NEWEST - dt.timedelta(days=5), NEWEST)
        jobs.do_backfill(self.ctx, self.target)
        # all missing days returned 0 rows (count as final) -> 28 days exist, so baseline written once
        b1 = self.ctx.conn.execute("SELECT * FROM baselines").fetchall()
        jobs.do_backfill(self.ctx, self.target)
        b2 = self.ctx.conn.execute("SELECT * FROM baselines").fetchall()
        self.assertEqual([tuple(r) for r in b1], [tuple(r) for r in b2])

    def test_resume_after_interruption_pulls_missing_dims_only(self):
        real = jobs.db.store_final
        calls = {"n": 0}

        def interrupt_on_second(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt
            return real(*a, **k)
        with mock.patch.object(jobs.db, "store_final", side_effect=interrupt_on_second):
            with self.assertRaises(KeyboardInterrupt):
                jobs.do_backfill(self.ctx, self.target)
        self.assertEqual(len(self.pulled()), 1)  # only OLDEST/site stored
        jobs.do_backfill(self.ctx, self.target)
        self.assertEqual(sorted(r["dims"] for r in self.pulled(OLDEST.isoformat())), ["page", "page_query", "site"])
        self.assertEqual(len(self.pulled()), 483 * 3)

    def test_nightly_pulls_only_missing_dates_and_never_repulls_final(self):
        jobs.do_backfill(self.ctx, self.target)
        n0 = len(self.ctx.gsc.calls)
        # one new final day appears, and one old day is deleted from coverage? inject a gap via a failed day
        self.ctx.gsc.first_incomplete = FID + dt.timedelta(days=1)
        health.start_job(self.ctx, "nightly")
        jobs.do_nightly(self.ctx, self.target)
        new_calls = [b for _, b in self.ctx.gsc.calls[n0:] if b["dimensions"] != ["date"]]
        self.assertEqual({b["startDate"] for b in new_calls}, {FID.isoformat()})
        self.assertEqual(len(new_calls), 3)

    def test_final_but_empty_is_deferred_and_retried(self):
        self.ctx.gsc.final_empty.add((P, NEWEST.isoformat()))
        jobs.do_backfill(self.ctx, self.target)
        self.assertEqual(self.pulled(NEWEST.isoformat()), [])
        errs = self.ctx.conn.execute("SELECT COUNT(*) FROM pulls WHERE status='error' AND error='final data not ready'"
                                     ).fetchone()[0]
        self.assertEqual(errs, 3)
        self.ctx.gsc.final_empty.clear()
        health.start_job(self.ctx, "nightly")
        jobs.do_nightly(self.ctx, self.target)
        self.assertEqual(len(self.pulled(NEWEST.isoformat())), 3)

    def test_trello_failure_still_runs_backup_and_stops_ping(self):
        jobs.do_backfill(self.ctx, self.target)
        self.ctx.trello.fail = True
        self.ctx.gsc.fail = [Exception("network down")]
        health.start_job(self.ctx, "nightly")
        with mock.patch.object(health, "ping_dead_man") as ping:
            ok = jobs.do_nightly(self.ctx, self.target)
        self.assertFalse(ok)
        step = {r["step"]: r["status"] for r in self.ctx.conn.execute(
            "SELECT step, status FROM runs WHERE parent_id=?", (self.ctx.job_run_id,))}
        self.assertEqual(step["backup"], "ok")
        self.assertEqual(step["pull:ex"], "error")
        ping.assert_not_called()

    def test_failure_alerts_once_per_day(self):
        jobs.do_backfill(self.ctx, self.target)
        for _ in range(2):
            self.ctx.gsc.fail = [Exception("network down")]
            health.start_job(self.ctx, "nightly")
            with mock.patch.object(health, "ping_dead_man"):
                jobs.do_nightly(self.ctx, self.target)
        self.assertEqual(len(self.trello.alert_cards()), 1)

    def test_ping_sent_when_all_good(self):
        jobs.do_backfill(self.ctx, self.target)
        health.start_job(self.ctx, "nightly")
        with mock.patch.object(health, "ping_dead_man") as ping:
            self.assertTrue(jobs.do_nightly(self.ctx, self.target))
        ping.assert_called_once()

    def test_writer_lock(self):
        lock = jobs.take_lock(self.ctx.cfg.data_dir)
        with self.assertRaises(jobs.AlreadyRunning):
            jobs.take_lock(self.ctx.cfg.data_dir)
        lock.close()
        jobs.take_lock(self.ctx.cfg.data_dir).close()

    def test_main_exit3_pings_for_nightly(self):
        os.environ["SHRIKE_CONFIG"] = self.ctx.cfg.path
        lock = jobs.take_lock(self.ctx.cfg.data_dir)
        try:
            with mock.patch.object(jobs, "load_secrets"), mock.patch.object(health, "ping_dead_man") as ping:
                self.assertEqual(jobs.main(["nightly"]), jobs.EXIT_RUNNING)
                ping.assert_called_once()
                self.assertEqual(jobs.main(["backfill"]), jobs.EXIT_RUNNING)
                self.assertEqual(ping.call_count, 1)
        finally:
            lock.close()
            del os.environ["SHRIKE_CONFIG"]

    def test_weekly_refused_in_phase0(self):
        os.environ["SHRIKE_CONFIG"] = self.ctx.cfg.path
        try:
            with mock.patch.object(jobs, "load_secrets"):
                self.assertEqual(jobs.main(["weekly"]), jobs.EXIT_CONFIG)
        finally:
            del os.environ["SHRIKE_CONFIG"]

    def test_crash_exit_code_is_not_treated_as_success(self):
        """A traceback must not exit with a code in SuccessExitStatus=10 3, or shrike-alert@ never fires."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = ("import sys; from unittest import mock; from shrike import jobs\n"
                "with mock.patch.object(jobs, 'load_secrets'), "
                "mock.patch.object(jobs, '_make_ctx', side_effect=RuntimeError('boom')):\n"
                "    sys.exit(jobs.main(['backfill']))\n")
        env = dict(os.environ, SHRIKE_CONFIG=self.ctx.cfg.path, PYTHONPATH=root)
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, cwd=root)
        self.assertNotIn(r.returncode, (0, 3, 10))
        self.assertIn(b"RuntimeError", r.stderr)
        with open(os.path.join(root, "deploy", "systemd", "shrike-backfill.service")) as f:
            self.assertIn("SuccessExitStatus=10 3", f.read())

    def test_render_units(self):
        out = jobs.render_units(self.ctx.cfg, self.t)
        self.assertEqual([os.path.basename(p) for p in out], ["shrike-nightly.timer"])
        with open(out[0]) as f:
            text = f.read()
        self.assertIn("OnCalendar=*-*-* 03:30:00 UTC", text)
        self.assertIn("WantedBy=timers.target", text)
        p1 = make_ctx(tmpdir(), phase=1)
        out = jobs.render_units(p1.cfg, self.t)
        with open([p for p in out if p.endswith("shrike-weekly.timer")][0]) as f:
            self.assertIn("OnCalendar=Mon *-*-* 07:00:00 UTC", f.read())


if __name__ == "__main__":
    gsc._sleep = lambda s: None
    unittest.main()
