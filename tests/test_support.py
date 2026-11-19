import datetime as dt
import unittest
from unittest import mock

from shrike import baseline, db, health, setup_check, trello
from shrike.errors import AuthError
from tests.fakes import FakeDrive, FakeSearchConsole, FakeTrello, make_ctx, make_data, media_bytes, tmpdir

UTC = dt.timezone.utc


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.trello = FakeTrello()
        self.ctx = make_ctx(tmpdir(), trello=self.trello)
        health.start_job(self.ctx, "nightly")

    def test_once_alerts_fire_once_and_daily_dedupes(self):
        for _ in range(3):
            health.alert(self.ctx, "truncated", "ex:2026-01-01", "m", "f", once=True)
            health.alert(self.ctx, "gap", "ex", "m", "f")
        self.assertEqual(len(self.trello.alert_cards()), 2)

    def test_undelivered_alert_counted_and_retried(self):
        self.trello.fail = True
        self.assertFalse(health.alert(self.ctx, "gap", "ex", "m", "f"))
        self.assertEqual(health.undelivered(self.ctx), 1)
        self.trello.fail = False
        self.assertTrue(health.alert(self.ctx, "gap", "ex", "m", "f"))

    def test_step_records_and_classifies(self):
        with health.step(self.ctx, "a") as s:
            raise AuthError("nope", "fix it")
        self.assertFalse(s.ok)
        kinds = [r["kind"] for r in self.ctx.conn.execute("SELECT kind FROM events")]
        self.assertEqual(kinds, ["auth"])
        with health.step(self.ctx, "b") as s2:
            pass
        self.assertTrue(s2.ok)

    def _range(self, first, last):
        db.set_range(self.ctx.conn, "ex", first_date=first, last_final_date=last)

    def test_checks_gap_expired_expiry_and_truncated(self):
        last = dt.date(2026, 3, 9)
        oldest = last - dt.timedelta(days=482)
        self._range((oldest - dt.timedelta(days=2)).isoformat(), last.isoformat())
        kinds = {p.kind for p in health.checks(self.ctx)}
        self.assertTrue({"gap", "expired", "expiry_warning"} <= kinds)
        db.store_final(self.ctx.conn, "ex", last.isoformat(), "page", [], True, db.utcnow())
        self.assertIn("truncated", {p.kind for p in health.checks(self.ctx)})

    def test_backup_stale_from_runs(self):
        now = dt.datetime.now(UTC)
        self.ctx.conn.execute("UPDATE runs SET started_at = ?", ((now - dt.timedelta(hours=60)).isoformat(),))
        self.assertIn("backup_stale", {p.kind for p in health.checks(self.ctx, now)})
        with health.step(self.ctx, "backup"):
            pass
        self.assertNotIn("backup_stale", {p.kind for p in health.checks(self.ctx, now)})

    def test_weekly_missing_uses_phase1_anchor(self):
        ctx = make_ctx(tmpdir(), phase=1)
        now = dt.datetime.now(UTC)
        self.assertNotIn("weekly_missing", {p.kind for p in health.checks(ctx, now)})
        db.meta_set_once(ctx.conn, "phase1_seen_at", (now - dt.timedelta(days=9)).isoformat())
        self.assertIn("weekly_missing", {p.kind for p in health.checks(ctx, now)})


class BaselineTest(unittest.TestCase):
    def test_compare(self):
        ctx = make_ctx(tmpdir())
        last = dt.date(2026, 3, 9)
        db.set_range(ctx.conn, "ex", first_date=(last - dt.timedelta(days=40)).isoformat(),
                     last_final_date=last.isoformat())
        for i in range(28):
            d = (last - dt.timedelta(days=i)).isoformat()
            db.store_final(ctx.conn, "ex", d, "site", [{"clicks": 10, "impressions": 100, "ctr": .1,
                                                        "position": 5.0}], False, db.utcnow())
        self.assertTrue(baseline.freeze(ctx.conn, "ex"))
        c = baseline.compare(ctx.conn, "ex")
        self.assertEqual(c["baseline"]["clicks"], 280)
        self.assertEqual(c["clicks_pct"], 0.0)


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.content = b"x" if body is not None else b""
        self.text = str(body)

    def json(self):
        return self._body


class TrelloClientTest(unittest.TestCase):
    def test_header_auth_retry_and_scrub(self):
        sess = mock.Mock()
        sess.request.side_effect = [FakeResp(429, headers={"Retry-After": "0"}), FakeResp(200, {"id": "c1"})]
        t = trello.Trello("KEY123", "TOK456", session=sess)
        with mock.patch.object(trello, "_sleep"):
            self.assertEqual(t.create_card("L", "n", "d"), "c1")
        _, kwargs = sess.request.call_args
        self.assertIn("oauth_token=\"TOK456\"", kwargs["headers"]["Authorization"])
        self.assertNotIn("TOK456", sess.request.call_args[0][1])
        sess.request.side_effect = [FakeResp(401)]
        with self.assertRaises(AuthError):
            t.get_list("L")
        sess.request.side_effect = Exception("boom https://api.trello.com/1/cards?key=KEY123&token=TOK456")
        try:
            t.get_list("L")
        except Exception as e:
            self.assertNotIn("TOK456", str(e))
            self.assertNotIn("KEY123", str(e))


class SetupCheckTest(unittest.TestCase):
    def test_full_report(self):
        tr = FakeTrello()
        ctx = make_ctx(tmpdir(), trello=tr, target="gdrive", dead_man_url="https://hc.example/x")
        gscc = FakeSearchConsole(dt.date(2026, 3, 10), make_data("sc-domain:ex.com", dt.date(2026, 3, 1),
                                                                  dt.date(2026, 3, 12)))
        from shrike import backup
        target = backup.DriveTarget(FakeDrive(), "fold", media_factory=media_bytes)
        checks = setup_check.full_report(ctx, gsc_client=gscc, drive_target=target)
        bad = [c for c in checks if not c.ok]
        self.assertEqual(bad, [])
        self.assertEqual(tr.cards, {})  # test card deleted

    def test_missing_dead_man_is_warning(self):
        ctx = make_ctx(tmpdir())
        gscc = FakeSearchConsole(dt.date(2026, 3, 10))
        checks = {c.name: c for c in setup_check.full_report(ctx, gsc_client=gscc)}
        self.assertTrue(checks["dead-man check"].warning)
        self.assertTrue(checks["backup target"].warning)  # local mode


if __name__ == "__main__":
    unittest.main()
