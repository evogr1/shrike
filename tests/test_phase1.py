import datetime as dt
import http.client
import json
import threading
import unittest
from unittest import mock

from shrike import db, fixes, jobs, mcp_remote, opps, routes, server
from shrike.config import Secrets
from tests.fakes import FakeTrello, make_ctx, tmpdir

LAST = dt.date(2026, 3, 31)
SMALL = """
            [opportunities]
            sd_min_impr = 50
            lowctr_min_impr = 200
            decay_min_clicks = 10
            [fixes]
            min_comparison_pages = 3
            min_before_impressions = 50
"""


def iso(back):
    return (LAST - dt.timedelta(days=back)).isoformat()


def row(page, clicks, impr, pos, query=None):
    r = {"page": page, "clicks": clicks, "impressions": impr, "ctr": clicks / impr if impr else 0, "position": pos}
    if query:
        r["query"] = query
    return r


class CardTrello(FakeTrello):
    def __init__(self):
        super().__init__(lists=("alerts", "inbox", "done"))
        self.moved = None

    def get_card(self, cid):
        return self.cards.get(cid)

    def update_card(self, cid, name, desc):
        self.cards[cid].update(name=name, desc=desc)

    def close_card(self, cid):
        self.cards[cid]["closed"] = True

    def last_move_date(self, cid, lid):
        return self.moved


def setup(days=70):
    trello = CardTrello()
    ctx = make_ctx(tmpdir(), trello=trello, phase=1, extra="" )
    with open(ctx.cfg.path) as f:
        text = f.read()
    text = text.replace('alert_list_id = "alerts"',
                        'alert_list_id = "alerts"\n            inbox_list_id = "inbox"\n            done_list_id = "done"')
    with open(ctx.cfg.path, "w") as f:
        f.write(text + SMALL)
    from shrike.config import load_config
    ctx.cfg = load_config(ctx.cfg.path)
    c = ctx.conn
    db.set_range(c, "ex", first_date=iso(days - 1), last_final_date=LAST.isoformat())
    for back in range(days):
        recent = back < 28
        pages = [row("https://ex.com/sd", 0, 5, 8.0), row("https://ex.com/low", 0, 20, 2.0),
                 row("https://ex.com/decay", 0 if recent else 1, 3, 9.0)]
        pq = [row("https://ex.com/sd", 0, 5, 8.0, "blue widgets")]
        db.store_final(c, "ex", iso(back), "site", [{"clicks": 1, "impressions": 28, "ctr": 0, "position": 5}],
                       False, db.utcnow())
        db.store_final(c, "ex", iso(back), "page", pages, False, db.utcnow())
        db.store_final(c, "ex", iso(back), "page_query", pq, False, db.utcnow())
    return ctx, trello


def run_weekly(ctx):
    from shrike import health
    health.start_job(ctx, "weekly")
    with mock.patch.object(jobs.backup, "verify_latest"):
        return jobs.do_weekly(ctx, lambda: None)


class OppsTest(unittest.TestCase):
    def test_three_rules_fire_and_thresholds_hold(self):
        ctx, _ = setup()
        found = {f["type"]: f for f in opps.find(ctx.conn, "ex", ctx.cfg, LAST.isoformat())}
        self.assertEqual(set(found), {"striking_distance", "low_ctr", "decaying"})
        self.assertEqual(found["striking_distance"]["query"], "blue widgets")
        self.assertEqual(found["low_ctr"]["page"], "https://ex.com/low")
        self.assertEqual(found["decaying"]["metrics"]["clicks_prev"], 28)
        self.assertEqual(found["striking_distance"]["metrics"]["benchmark"], "a generic benchmark")
        ctx.cfg.opp.update(sd_min_impr=10**6, lowctr_min_impr=10**6, decay_min_clicks=10**6)
        self.assertEqual(opps.find(ctx.conn, "ex", ctx.cfg, LAST.isoformat()), [])

    def test_position_bands(self):
        bands = [[1, 1], [2, 2], [3, 3], [4, 5], [6, 10], [11, 20]]
        self.assertEqual(opps.band_of(2.5, bands), 2)
        self.assertEqual(opps.band_of(20.4, bands), 5)
        self.assertIsNone(opps.band_of(20.5, bands))


class WeeklyTest(unittest.TestCase):
    def status(self, ctx):
        return {r["type"]: r["status"] for r in ctx.conn.execute("SELECT type, status FROM opportunities")}

    def test_brief_lifecycle(self):
        ctx, trello = setup()
        self.assertTrue(run_weekly(ctx))
        cards = [c for c in trello.cards.values() if c["idList"] == "inbox"]
        self.assertEqual(len(cards), 4)  # summary + 3 fixes
        self.assertEqual(set(self.status(ctx).values()), {"sent"})
        sd = next(c for c in cards if "Striking" in c["name"])
        sd["desc"] += "\nshipped: 2026-02-20"
        run_weekly(ctx)  # not re-sent, open card refreshed, shipped line kept
        self.assertEqual(len([c for c in trello.cards.values() if c["idList"] == "inbox"]), 5)
        self.assertIn("shipped: 2026-02-20", trello.cards[sd["id"]]["desc"])
        sd["idList"] = "done"
        low = next(c for c in cards if "Low CTR" in c["name"])
        low["closed"] = True
        self.assertEqual(fixes.sync_from_trello(ctx.conn, trello, ctx.cfg), (1, 1))
        fix = ctx.conn.execute("SELECT * FROM fixes").fetchone()
        self.assertEqual((fix["ship_date"], fix["ship_date_source"]), ("2026-02-20", "card_line"))
        trello.cards[sd["id"]]["closed"] = True  # archiving a Done card changes nothing
        fixes.sync_from_trello(ctx.conn, trello, ctx.cfg)
        self.assertEqual(self.status(ctx)["striking_distance"], "done")
        self.assertEqual(self.status(ctx)["low_ctr"], "dismissed")

    def test_expiry_closes_card_and_resend_waits(self):
        ctx, trello = setup()
        run_weekly(ctx)
        for run in (101, 102, 103):
            opps.upsert(ctx.conn, ctx.cfg, [], trello, run)
        self.assertEqual(set(self.status(ctx).values()), {"expired"})
        self.assertTrue(any(c["closed"] for c in trello.cards.values()))
        found = opps.find(ctx.conn, "ex", ctx.cfg, LAST.isoformat())
        opps.upsert(ctx.conn, ctx.cfg, found, trello, 104)
        self.assertEqual(set(self.status(ctx).values()), {"expired"})
        later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(weeks=9)
        opps.upsert(ctx.conn, ctx.cfg, found, trello, 105, now=later)
        self.assertEqual(set(self.status(ctx).values()), {"new"})

    def test_dry_run_writes_nothing(self):
        ctx, trello = setup()
        with mock.patch("builtins.print"):
            self.assertEqual(jobs.preview(ctx.cfg, ctx.cfg.db_path), 3)
        self.assertEqual(trello.cards, {})
        self.assertEqual(ctx.conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0], 0)


class MeasureTest(unittest.TestCase):
    def test_effect_matches_worked_example_and_exclusions(self):
        ctx = make_ctx(tmpdir())
        ctx.cfg.fix.update(min_comparison_pages=3)
        c, ship = ctx.conn, LAST - dt.timedelta(days=28)
        db.set_range(c, "ex", first_date=iso(60), last_final_date=LAST.isoformat())
        for offset, mult in ((-10, 0), (10, 1)):
            rows = [row("fixed", [400, 500][mult], 1000, 3)]
            rows += [row(f"c{i}", [100, 105][mult], 1000, 3) for i in range(4)]
            db.store_final(c, "ex", (ship + dt.timedelta(days=offset)).isoformat(), "page", rows, False, db.utcnow())
        fix = {"site": "ex", "page": "fixed", "ship_date": ship.isoformat()}
        r = fixes.measure_one(c, ctx.cfg, fix)
        self.assertAlmostEqual(r["effect_clicks"], 80.0)
        self.assertEqual((r["included"], r["group_size"]), (1, 4))
        ctx.cfg.fix.update(min_comparison_pages=10)
        self.assertEqual(fixes.measure_one(c, ctx.cfg, fix)["exclusion_reason"], "too few comparison pages")
        r = fixes.measure_one(c, ctx.cfg, {**fix, "page": "nothing"})
        self.assertEqual(r["exclusion_reason"], "too little data")


class ServerTest(unittest.TestCase):
    KEY, SECRET = "k" * 30, "s" * 30

    def setUp(self):
        ctx, trello = setup()
        run_weekly(ctx)
        self.sctx = routes.ServerContext(ctx.cfg, Secrets(api_key=self.KEY, mcp_secret=self.SECRET))
        self.srv = server.make_server(self.sctx, "127.0.0.1", 0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.log = []
        p = mock.patch.object(server.sys, "stderr", mock.Mock(write=self.log.append))
        p.start()
        self.addCleanup(p.stop)

    def req(self, method, path, body=None, key=KEY):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers={"X-API-Key": key} if key else {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, json.loads(data) if data else None

    def test_auth_errors_and_routes(self):
        self.assertEqual(self.req("GET", "/v1/nope", key="")[0], 401)
        self.assertEqual(self.req("GET", "/v1/nope")[0], 404)
        self.assertEqual(self.req("DELETE", "/v1/sites")[0], 405)
        self.assertEqual(self.req("GET", "/v1/performance")[0], 400)
        self.assertEqual(self.req("GET", "/v1/performance?site=ex&bogus=1")[0], 400)
        for path in ("/v1/setup", "/v1/sites", "/v1/opportunities", "/v1/fixes", "/v1/health", "/health"):
            self.assertEqual(self.req("GET", path)[0], 200, path)
        status, body = self.req("GET", "/v1/performance?site=ex&group_by=page&compare=prev_period&limit=2")
        self.assertEqual((status, len(body["rows"]), body["next_offset"]), (200, 2, 2))
        self.assertIn("compare", body["rows"][0])
        self.assertEqual(len(self.req("GET", "/v1/opportunities")[1]["opportunities"]), 3)

    def test_job_start_and_conflict(self):
        def fake(state):
            return lambda *a: mock.Mock(stdout=state if a[0] == "show" else "", returncode=0)
        with mock.patch.object(routes, "_systemctl", side_effect=fake("inactive")):
            self.assertEqual(self.req("POST", "/v1/jobs", {"job": "nightly"})[0], 202)
        with mock.patch.object(routes, "_systemctl", side_effect=fake("activating\n")):
            self.assertEqual(self.req("POST", "/v1/jobs", {"job": "nightly"})[0], 409)

    def test_remote_mcp(self):
        listing = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        self.assertEqual(self.req("POST", "/mcp/wrong", listing, key="")[0], 404)
        status, body = self.req("POST", f"/mcp/{self.SECRET}", listing, key="")
        names = [t["name"] for t in body["result"]["tools"]]
        self.assertEqual((status, len(names)), (200, 6))
        self.assertNotIn("shrike_run_job", names)
        note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self.assertEqual(self.req("POST", f"/mcp/{self.SECRET}", note, key="")[0], 202)
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "shrike_sites", "arguments": {}}}
        self.assertFalse(self.req("POST", f"/mcp/{self.SECRET}", call, key="")[1]["result"]["isError"])
        self.assertNotIn(self.SECRET, "".join(self.log))
        self.assertEqual(len(mcp_remote.tools(False)), 7)


if __name__ == "__main__":
    unittest.main()
