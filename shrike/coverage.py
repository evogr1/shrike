"""Which (date, dimension set) pairs still need a final pull (design C2, C4)."""


def todo(conn, site, oldest):
    """Missing (date, dims) pairs at or after today's oldest available date, oldest first."""
    rows = conn.execute(
        "SELECT date, dims FROM v_coverage WHERE site = ? AND state = 'missing' AND date >= ?"
        " ORDER BY date, CASE dims WHEN 'site' THEN 0 WHEN 'page' THEN 1 ELSE 2 END",
        (site, oldest),
    ).fetchall()
    return [(r["date"], r["dims"]) for r in rows]


def expired(conn, site, oldest):
    """Dates that were never pulled and are now older than Google keeps."""
    rows = conn.execute(
        "SELECT DISTINCT date FROM v_coverage WHERE site = ? AND state = 'missing' AND date < ? ORDER BY date",
        (site, oldest),
    ).fetchall()
    return [r["date"] for r in rows]


def oldest_missing(conn, site, oldest):
    r = conn.execute(
        "SELECT MIN(date) AS d FROM v_coverage WHERE site = ? AND state = 'missing' AND date >= ?",
        (site, oldest),
    ).fetchone()
    return r["d"]


def missing_days(conn, site):
    r = conn.execute(
        "SELECT COUNT(DISTINCT date) AS n FROM v_coverage WHERE site = ? AND state = 'missing'", (site,)
    ).fetchone()
    return r["n"]


def truncated_days(conn, site):
    rows = conn.execute(
        "SELECT DISTINCT date FROM v_coverage WHERE site = ? AND state = 'truncated' ORDER BY date", (site,)
    ).fetchall()
    return [r["date"] for r in rows]


def gaps_older_than(conn, site, cutoff):
    """Missing dates strictly before cutoff (used for the 'gap' alert)."""
    rows = conn.execute(
        "SELECT DISTINCT date FROM v_coverage WHERE site = ? AND state = 'missing' AND date < ? ORDER BY date",
        (site, cutoff),
    ).fetchall()
    return [r["date"] for r in rows]


def final_count(conn, site):
    r = conn.execute(
        "SELECT COUNT(*) AS n FROM v_coverage WHERE site = ? AND state IN ('final', 'truncated')", (site,)
    ).fetchone()
    return r["n"]
