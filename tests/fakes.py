"""In-memory fakes for Search Console, Trello and Drive. No test touches the network."""

import datetime as dt
import json
import os
import tempfile
import textwrap

from shrike import db, gsc
from shrike.config import load_config
from shrike.health import JobContext


class FakeHttpError(Exception):
    def __init__(self, status, reason=""):
        super().__init__(f"HTTP {status} {reason}")
        self.resp = type("R", (), {"status": status})()
        self.content = json.dumps({"error": {"errors": [{"reason": reason}] if reason else []}}).encode()


class FakeSearchConsole:
    """data[(prop, date)] = {"clicks":..,"impressions":.., "pages": {page: {query: (clicks, impr)}}}"""

    def __init__(self, first_incomplete, data=None):
        self.first_incomplete = first_incomplete
        self.data = data or {}
        self.calls = []
        self.fail = []            # list of exceptions to raise on next calls
        self.final_empty = set()  # (prop, date) that return no final rows yet

    def searchanalytics(self):
        return self

    def query(self, siteUrl, body):
        self._req = (siteUrl, body)
        return self

    def execute(self):
        prop, body = self._req
        self.calls.append((prop, dict(body)))
        if self.fail:
            raise self.fail.pop(0)
        dims = body["dimensions"]
        if dims == ["date"]:
            start, end = dt.date.fromisoformat(body["startDate"]), dt.date.fromisoformat(body["endDate"])
            rows = []
            d = start
            while d <= end:
                rec = self.data.get((prop, d.isoformat()))
                if rec and d < self.first_incomplete + dt.timedelta(days=2):
                    rows.append({"keys": [d.isoformat()], "clicks": rec["clicks"], "impressions": rec["impressions"]})
                d += dt.timedelta(days=1)
            return {"rows": rows, "metadata": {"firstIncompleteDate": self.first_incomplete.isoformat()}}
        date = body["startDate"]
        rec = self.data.get((prop, date))
        if not rec or (prop, date) in self.final_empty:
            return {}
        if dims == []:
            rows = [{"clicks": rec["clicks"], "impressions": rec["impressions"], "ctr": 0.05, "position": 8.0}]
        elif dims == ["page"]:
            rows = [{"keys": [p], "clicks": sum(c for c, _ in qs.values()), "impressions": sum(i for _, i in qs.values()),
                     "ctr": 0.05, "position": 8.0} for p, qs in rec["pages"].items()]
        else:
            rows = [{"keys": [p, q], "clicks": c, "impressions": i, "ctr": c / i if i else 0, "position": 7.0}
                    for p, qs in rec["pages"].items() for q, (c, i) in qs.items()]
        start = body.get("startRow", 0)
        return {"rows": rows[start:start + body["rowLimit"]]}


def make_data(prop, start, end, pages=2):
    data, d = {}, start
    while d <= end:
        pg = {f"https://ex.com/p{i}": {f"q{i}a": (3, 60), f"q{i}b": (1, 40)} for i in range(pages)}
        data[(prop, d.isoformat())] = {"clicks": 4 * pages, "impressions": 100 * pages, "pages": pg}
        d += dt.timedelta(days=1)
    return data


class FakeTrello:
    def __init__(self, lists=("alerts",), fail=False):
        self.lists = {lid: {"id": lid, "name": lid} for lid in lists}
        self.cards = {}
        self.fail = fail
        self.n = 0

    def _maybe_fail(self):
        if self.fail:
            from shrike.errors import AuthError

            raise AuthError("Trello refused the key or token", "new token")

    def get_list(self, list_id):
        self._maybe_fail()
        return self.lists.get(list_id)

    def create_card(self, list_id, name, desc):
        self._maybe_fail()
        self.n += 1
        cid = f"c{self.n}"
        self.cards[cid] = {"id": cid, "idList": list_id, "name": name, "desc": desc, "closed": False}
        return cid

    def delete_card(self, card_id):
        self._maybe_fail()
        self.cards.pop(card_id, None)

    def alert_cards(self):
        return [c for c in self.cards.values() if c["idList"] == "alerts"]


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeDrive:
    """Mimics the googleapiclient files() call chain and records every call's kwargs."""

    def __init__(self, folder_id="fold", allow_permanent_delete=False):
        self.folder_id = folder_id
        self.store = {}   # id -> (name, bytes, trashed)
        self.calls = []
        self.allow_permanent_delete = allow_permanent_delete
        self.n = 0

    def files(self):
        return self

    def _rec(self, op, kw):
        self.calls.append((op, kw))

    def get(self, **kw):
        self._rec("get", kw)
        return _Req(lambda: {"driveId": "sharedX"})

    def create(self, body, media_body, **kw):
        self._rec("create", kw)

        def go():
            self.n += 1
            fid = f"f{self.n}"
            self.store[fid] = [body["name"], media_body, False]
            return {"id": fid}
        return _Req(go)

    def list(self, **kw):
        self._rec("list", kw)
        return _Req(lambda: {"files": [{"id": k, "name": v[0]} for k, v in self.store.items() if not v[2]]})

    def update(self, fileId, body, **kw):
        self._rec("update", kw)

        def go():
            self.store[fileId][2] = bool(body.get("trashed"))
            return {}
        return _Req(go)

    def get_media(self, fileId, **kw):
        self._rec("get_media", kw)
        return _Req(lambda: self.store[fileId][1])

    def delete(self, fileId, **kw):
        self._rec("delete", kw)

        def go():
            if not self.allow_permanent_delete:
                raise FakeHttpError(403, "insufficientFilePermissions")
            self.store.pop(fileId)
            return {}
        return _Req(go)


def media_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def write_config(tmp, **over):
    vals = {"phase": 0, "target": "local", "dead_man_url": "", "extra": ""}
    vals.update(over)
    path = os.path.join(tmp, "config.toml")
    with open(path, "w") as f:
        f.write(textwrap.dedent(f"""
            [general]
            phase = {vals['phase']}
            timezone = "UTC"
            data_dir = "{tmp}/data"
            dead_man_url = "{vals['dead_man_url']}"

            [[sites]]
            name = "ex"
            property = "sc-domain:ex.com"

            [pull]
            pull_pause_seconds = 0

            [trello]
            alert_list_id = "alerts"

            [backup]
            target = "{vals['target']}"
            gdrive_folder_id = "fold"
            local_path = "{tmp}/backups"
            {vals['extra']}
            """))
    return path


def make_ctx(tmp, trello=None, gsc_client=None, **cfg_over):
    cfg = load_config(write_config(tmp, **cfg_over))
    conn = db.connect(cfg.db_path)
    db.migrate(conn, cfg.data_dir)
    return JobContext(conn=conn, cfg=cfg, secrets=None, trello=trello or FakeTrello(), gsc=gsc_client)


def tmpdir():
    return tempfile.mkdtemp(prefix="shrike-test-")


gsc._sleep = lambda s: None  # no real sleeping in tests
