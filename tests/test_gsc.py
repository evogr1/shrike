import datetime as dt
import unittest

from shrike import gsc
from shrike.errors import AuthError, QuotaError
from tests.fakes import FakeHttpError, FakeSearchConsole, make_data

P = "sc-domain:ex.com"


class PagingClient(FakeSearchConsole):
    def __init__(self, total):
        super().__init__(dt.date(2026, 3, 10))
        self.total = total

    def execute(self):
        prop, body = self._req
        self.calls.append(body)
        n = max(0, min(body["rowLimit"], self.total - body["startRow"]))
        return {"rows": [{"keys": [f"p{body['startRow'] + i}", "q"], "clicks": 1, "impressions": 1, "ctr": 1,
                          "position": 1} for i in range(n)]}


class GscTest(unittest.TestCase):
    def test_paging_stops_on_short_page(self):
        c = PagingClient(30000)
        rows, trunc = gsc.fetch_day(c, P, "2026-03-01", "page_query")
        self.assertEqual(len(rows), 30000)
        self.assertEqual([b["startRow"] for b in c.calls], [0, 25000])
        self.assertFalse(trunc)

    def test_truncation_at_50k_not_at_25k(self):
        self.assertTrue(gsc.fetch_day(PagingClient(50000), P, "2026-03-01", "page")[1])
        self.assertFalse(gsc.fetch_day(PagingClient(25000), P, "2026-03-01", "page")[1])

    def test_429_retried_then_quota_error(self):
        c = FakeSearchConsole(dt.date(2026, 3, 10), make_data(P, dt.date(2026, 3, 1), dt.date(2026, 3, 1)))
        c.fail = [FakeHttpError(429)] * 6
        with self.assertRaises(QuotaError):
            gsc.fetch_day(c, P, "2026-03-01", "site")
        c.fail = [FakeHttpError(429), FakeHttpError(403, "rateLimitExceeded")]
        rows, _ = gsc.fetch_day(c, P, "2026-03-01", "site")
        self.assertEqual(len(rows), 1)

    def test_403_other_reason_is_auth(self):
        c = FakeSearchConsole(dt.date(2026, 3, 10))
        c.fail = [FakeHttpError(403, "forbidden")]
        with self.assertRaises(AuthError) as cm:
            gsc.fetch_day(c, P, "2026-03-01", "site", auth_fix="add sa@x as a Restricted user")
        self.assertIn("Restricted", cm.exception.fix_step)

    def test_probe_reads_first_incomplete_and_falls_back(self):
        c = FakeSearchConsole(dt.date(2026, 3, 10), make_data(P, dt.date(2026, 3, 1), dt.date(2026, 3, 12)))
        fid, impr = gsc.probe(c, P, today=dt.date(2026, 3, 12))
        self.assertEqual(fid, dt.date(2026, 3, 10))
        self.assertIn("2026-03-09", impr)

        class NoMeta(FakeSearchConsole):
            def execute(self):
                return {"rows": []}
        fid, _ = gsc.probe(NoMeta(None), P, today=dt.date(2026, 3, 12))
        self.assertEqual(fid, dt.date(2026, 3, 9))

    def test_available_range(self):
        oldest, newest = gsc.available_range(dt.date(2026, 3, 10))
        self.assertEqual(newest, dt.date(2026, 3, 9))
        self.assertEqual((newest - oldest).days, 482)


if __name__ == "__main__":
    unittest.main()
