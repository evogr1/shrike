"""Trello REST client (design C12). Credentials go in a header, never in the URL."""

import datetime as dt
import re
import time

from .errors import AuthError, UpstreamError

API = "https://api.trello.com/1"
_SCRUB = re.compile(r"(key|token|oauth_consumer_key|oauth_token)=([\"']?)[^&\s\"',]+")
_sleep = time.sleep


def scrub(text):
    return _SCRUB.sub(lambda m: f"{m.group(1)}={m.group(2)}***", str(text))


class Trello:
    def __init__(self, key, token, timeout=30, session=None):
        self._auth = f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"'
        self._secrets = (key, token)
        self.timeout = timeout
        if session is None:
            import requests

            session = requests.Session()
        self.s = session

    def _clean(self, text):
        text = scrub(text)
        for sec in self._secrets:
            if sec:
                text = text.replace(sec, "***")
        return text

    def _req(self, method, path, **kw):
        for attempt in range(4):
            try:
                r = self.s.request(method, API + path, headers={"Authorization": self._auth},
                                   timeout=self.timeout, **kw)
            except Exception as e:
                raise UpstreamError(self._clean(f"Trello request failed: {e!r}"), "check network access to api.trello.com") from None
            if r.status_code == 429 and attempt < 3:
                _sleep(float(r.headers.get("Retry-After", 10)))
                continue
            if r.status_code in (401, 403):
                raise AuthError("Trello refused the key or token", "create a new token and update SK_TRELLO_TOKEN")
            if r.status_code == 404:
                return None
            if r.status_code >= 400:
                raise UpstreamError(self._clean(f"Trello HTTP {r.status_code}: {r.text[:200]}"), "check the list and board ids")
            return r.json() if r.content else {}
        raise UpstreamError("Trello kept rate-limiting", "wait and retry")

    def get_list(self, list_id):
        return self._req("GET", f"/lists/{list_id}")

    def create_card(self, list_id, name, desc):
        card = self._req("POST", "/cards", params={"idList": list_id, "name": name[:16384], "desc": desc[:16384]})
        if not card:
            raise UpstreamError(f"Trello list {list_id} not found", "check the list id in config.toml")
        return card["id"]

    def update_card(self, card_id, name, desc):
        return self._req("PUT", f"/cards/{card_id}", params={"name": name, "desc": desc})

    def get_card(self, card_id):
        return self._req("GET", f"/cards/{card_id}", params={"fields": "idList,closed,desc,dateLastActivity"})

    def last_move_date(self, card_id, to_list_id):
        acts = self._req("GET", f"/cards/{card_id}/actions", params={"filter": "updateCard:idList"}) or []
        for a in acts:  # newest first
            if a.get("data", {}).get("listAfter", {}).get("id") == to_list_id:
                return _parse(a["date"])
        card = self.get_card(card_id) or {}
        return _parse(card["dateLastActivity"]) if card.get("dateLastActivity") else None

    def close_card(self, card_id):
        return self._req("PUT", f"/cards/{card_id}", params={"closed": "true"})

    def delete_card(self, card_id):
        return self._req("DELETE", f"/cards/{card_id}")


def _parse(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
