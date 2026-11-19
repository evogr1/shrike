"""SQLite access: connections, migrations and the only write paths for raw data."""

import datetime as dt
import glob
import os
import re
import sqlite3
from importlib import resources

BUSY_MS = 10000


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_MS / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_MS}")
    return conn


def connect_ro(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=BUSY_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_MS}")
    return conn


def _migrations():
    files = resources.files("sk.migrations")
    out = []
    for f in files.iterdir():
        m = re.match(r"^(\d{3})_.*\.sql$", f.name)
        if m:
            out.append((int(m.group(1)), f))
    return sorted(out, key=lambda x: x[0])


def schema_version(conn):
    try:
        return conn.execute("SELECT version FROM schema_version").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def latest_version():
    m = _migrations()
    return m[-1][0] if m else 0


def migrate(conn, data_dir=None):
    """Apply pending migrations. Takes a pre-migrate snapshot when the database already has data."""
    current = schema_version(conn)
    pending = [(n, f) for n, f in _migrations() if n > current]
    if not pending:
        return []
    if current > 0 and data_dir:
        snap = os.path.join(data_dir, f"pre-migrate-{current}.sqlite")
        snapshot(conn, snap)
        olds = sorted(glob.glob(os.path.join(data_dir, "pre-migrate-*.sqlite")), key=os.path.getmtime)
        for old in olds[:-3]:
            os.remove(old)
    done = []
    for n, f in pending:
        sql = f.read_text()
        try:
            conn.executescript(f"BEGIN;\n{sql}\nUPDATE schema_version SET version = {n};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        done.append(n)
    return done


def snapshot(conn, dest_path):
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    dest = sqlite3.connect(dest_path)
    try:
        conn.backup(dest)
    finally:
        dest.close()


TABLE_FOR = {"site": "gsc_site", "page": "gsc_page", "page_query": "gsc_page_query"}
COLS_FOR = {
    "site": ("site", "date", "clicks", "impressions", "ctr", "position"),
    "page": ("site", "date", "page", "clicks", "impressions", "ctr", "position"),
    "page_query": ("site", "date", "page", "query", "clicks", "impressions", "ctr", "position"),
}


def store_final(conn, site, date, dims, rows, truncated, started_at):
    """Insert one successful final pull and its rows in a single transaction. Returns the pull id."""
    table, cols = TABLE_FOR[dims], COLS_FOR[dims]
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "INSERT INTO pulls (site, date, dims, data_state, status, row_count, truncated, started_at, finished_at)"
            " VALUES (?, ?, ?, 'final', 'ok', ?, ?, ?, ?)",
            (site, date, dims, len(rows), 1 if truncated else 0, started_at, utcnow()),
        )
        pull_id = cur.lastrowid
        q = f"INSERT INTO {table} ({', '.join(cols)}, pull_id) VALUES ({', '.join('?' * (len(cols) + 1))})"
        conn.executemany(q, [tuple(r[c] if c not in ("site", "date") else (site if c == "site" else date)
                                   for c in cols) + (pull_id,) for r in rows])
        conn.execute("COMMIT")
        return pull_id
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_failed_pull(conn, site, date, dims, error, started_at):
    conn.execute(
        "INSERT INTO pulls (site, date, dims, data_state, status, error, started_at, finished_at)"
        " VALUES (?, ?, ?, 'final', 'error', ?, ?, ?)",
        (site, date, dims, str(error)[:2000], started_at, utcnow()),
    )


def set_range(conn, site, first_date=None, last_final_date=None):
    """first_date is write-once; last_final_date is refreshed."""
    conn.execute(
        "INSERT INTO site_range (site, first_date, last_final_date, updated_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(site) DO UPDATE SET"
        "  first_date = COALESCE(site_range.first_date, excluded.first_date),"
        "  last_final_date = COALESCE(excluded.last_final_date, site_range.last_final_date),"
        "  updated_at = excluded.updated_at",
        (site, first_date, last_final_date, utcnow()),
    )


def get_range(conn, site):
    r = conn.execute("SELECT first_date, last_final_date FROM site_range WHERE site = ?", (site,)).fetchone()
    return (r["first_date"], r["last_final_date"]) if r else (None, None)


def meta_get(conn, key):
    r = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def meta_set_once(conn, key, value):
    conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, value))
