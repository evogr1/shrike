import os
import sqlite3
import unittest

from shrike import coverage, db
from tests.fakes import tmpdir


class DbTest(unittest.TestCase):
    def setUp(self):
        self.t = tmpdir()
        self.conn = db.connect(os.path.join(self.t, "d.sqlite"))
        db.migrate(self.conn, self.t)

    def test_migrate_is_idempotent(self):
        self.assertEqual(db.schema_version(self.conn), db.latest_version())
        self.assertEqual(db.migrate(self.conn, self.t), [])

    def test_coverage_reports_missing_for_never_pulled(self):
        db.set_range(self.conn, "ex", first_date="2026-01-01", last_final_date="2026-01-03")
        rows = self.conn.execute("SELECT state FROM v_coverage WHERE site='ex'").fetchall()
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(r["state"] == "missing" for r in rows))

    def test_final_truncated_and_zero_rows(self):
        db.set_range(self.conn, "ex", first_date="2026-01-01", last_final_date="2026-01-01")
        db.store_final(self.conn, "ex", "2026-01-01", "site", [], False, db.utcnow())
        db.store_final(self.conn, "ex", "2026-01-01", "page", [{"page": "p", "clicks": 1, "impressions": 2,
                                                                "ctr": .5, "position": 3.0}], True, db.utcnow())
        st = {r["dims"]: r["state"] for r in self.conn.execute("SELECT dims, state FROM v_coverage")}
        self.assertEqual(st, {"site": "final", "page": "truncated", "page_query": "missing"})

    def test_coverage_counters(self):
        db.set_range(self.conn, "ex", first_date="2026-01-01", last_final_date="2026-01-02")
        for dims in ("site", "page", "page_query"):
            db.store_final(self.conn, "ex", "2026-01-01", dims, [], False, db.utcnow())
        self.assertEqual(coverage.missing_days(self.conn, "ex"), 1)
        self.assertEqual(coverage.final_count(self.conn, "ex"), 3)
        self.assertEqual(coverage.todo(self.conn, "ex", "2026-01-01"),
                         [("2026-01-02", "site"), ("2026-01-02", "page"), ("2026-01-02", "page_query")])

    def test_first_date_is_write_once(self):
        db.set_range(self.conn, "ex", first_date="2026-01-01", last_final_date="2026-01-05")
        db.set_range(self.conn, "ex", first_date="2026-02-01", last_final_date="2026-02-05")
        self.assertEqual(db.get_range(self.conn, "ex"), ("2026-01-01", "2026-02-05"))

    def test_final_rows_are_append_only(self):
        db.store_final(self.conn, "ex", "2026-01-01", "site", [{"clicks": 1, "impressions": 2, "ctr": .5,
                                                                "position": 3.0}], False, db.utcnow())
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE gsc_site SET clicks = 9")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM gsc_site")

    def test_second_ok_pull_rejected(self):
        db.store_final(self.conn, "ex", "2026-01-01", "site", [], False, db.utcnow())
        with self.assertRaises(sqlite3.IntegrityError):
            db.store_final(self.conn, "ex", "2026-01-01", "site", [], False, db.utcnow())

    def test_premigrate_snapshot_and_rollback(self):
        class F:
            def __init__(self, name, sql):
                self.name, self._sql = name, sql

            def read_text(self):
                return self._sql

        orig = db._migrations
        try:
            db._migrations = lambda: orig() + [(2, F("002_bad.sql", "CREATE TABLE zz (x); CREATE TABLE zz (x);"))]
            with self.assertRaises(sqlite3.OperationalError):
                db.migrate(self.conn, self.t)
            self.assertTrue(os.path.exists(os.path.join(self.t, "pre-migrate-1.sqlite")))
            self.assertEqual(db.schema_version(self.conn), 1)
            self.assertIsNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name='zz'").fetchone())
        finally:
            db._migrations = orig


if __name__ == "__main__":
    unittest.main()
